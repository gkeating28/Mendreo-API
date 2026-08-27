import json
import logging
import os
import random
import re
import time
import traceback
from datetime import timedelta
from typing import Optional, List

from dataclasses import dataclass

from django.utils import timezone
from pydantic import BaseModel, Field

from pydantic_ai import Agent, RunContext, UsageLimits

from .AI import AI, SessionAiResponse, SummaryAiResponse
from .AiProviderFactory import build_pydantic_model, run_with_failover

from ..asset.models import Asset
from ..setting.models import Setting

from ..consumer.models import Consumer
from ..message.models import Message
from ..exercise_summary.models import Exercise, ExerciseSummary
from ..session.serializers import Session, SessionDetailSerializer

from ..utils import DateUtils, Constants, S3 as S3Utils
from .SuggestedResponses import sanitize_suggested_responses

PROMPT_DATE_FORMAT = "%d %B, %Y"
STATIC_FILES_DIR = 'api/utils/files'
SUMMARY_RESPONSE_SCHEMA = SummaryAiResponse
SESSION_RESPONSE_SCHEMA = SessionAiResponse

logger = logging.getLogger(__name__)


@dataclass
class Dependencies:
    session: Session
    consumer: Consumer
    exercise: Optional[Exercise]
    asset: Optional[Asset] = None
    matched_exercise: Optional[Exercise] = None


class GeneralResponse(BaseModel):
    text: str = Field(
      description="""Required. A text based response to your clients question""",
    )
    suggested_responses: Optional[List] = Field(
        description=(
            "Optional. Up to 3 tap-to-send replies in the client's own voice, each 1–4 words. "
            "These are answers the client would send back, never your question restated. "
            "If `text` asks something, chips must answer it "
            '(e.g. text: "When would evenings or weekends work?" → ["Tonight", "This weekend"]). '
            'Also allowed: "Tell me more", "I don\'t understand". '
            'Never use a question or prompt label ("When can you work?", "How are you feeling?"). '
            "Omit this field rather than filling it with questions."
        )
    )
    reasoning: str = Field(
      description="""Required. Why you chose this response include clear references""",
    )
    asset_id: Optional[str] = Field(default=None, description="Optional. An asset id")


class ExerciseResponse(GeneralResponse):
    step_no: int = Field(
        ...,
        description="Required. The current step number in the exercise (1-based index)."
    )
    is_step_complete: bool = Field(
        ...,
        description="Required. Whether the current step has been completed successfully,user must have been confirm they are ready proceed to the next step if this is not the last step."
    )
    completion_result: Optional[str] = Field(
        description=(
            "Required when is_step_complete is true. The user's captured answer for this "
            "step (what COMPLETION_PROMPT asked them to produce), in their own words. "
            "Quote the substance from earlier in the step if the latest message is only "
            "yes/ok to proceed. Never N/A, None, unknown, or similar placeholders."
        )
    )


SKIP_COMPLETION_RESULT = "Step Skipped"
_COMPLETION_RESULT_MAX_LEN = 400

_PLACEHOLDER_COMPLETION = re.compile(
    r"^(n/?a\.?|n\.a\.|na|none|null|nil|-|unknown|not sure|nothing)$",
    re.IGNORECASE,
)
_STEP_COMPLETED_PLACEHOLDER = re.compile(
    r"^step\s+\d+(\s+of\s+\d+)?\s+completed\.?$",
    re.IGNORECASE,
)
_PROCEED_CONFIRMATION = re.compile(
    r"^(y|yes|yeah|yep|yup|ok|okay|k|sure|ready|continue|next|"
    r"let'?s go|lets go|go ahead|please|do it|i('?m| am) ready|"
    r"sounds good|alright|all right)[\s!.]*$",
    re.IGNORECASE,
)
_QA_COMMAND_TEXTS = {
    "qa skip step",
    "qa asset image",
    "qa asset post",
    "qa asset file",
    "qa exercise",
}


def is_usable_completion_result(value: Optional[str]) -> bool:
    """True when the model (or a user turn) is a real captured answer, not a placeholder."""
    text = (value or "").strip()
    if not text:
        return False
    if text.lower() in _QA_COMMAND_TEXTS:
        return False
    if _PLACEHOLDER_COMPLETION.match(text):
        return False
    if _STEP_COMPLETED_PLACEHOLDER.match(text):
        return False
    if _PROCEED_CONFIRMATION.match(text):
        return False
    return True


def pick_completion_result_from_texts(texts: List[str]) -> Optional[str]:
    """Newest-first: first substantial user utterance, skipping yes/ok and placeholders."""
    for raw in texts:
        text = (raw or "").strip()
        if not is_usable_completion_result(text):
            continue
        if len(text) > _COMPLETION_RESULT_MAX_LEN:
            text = text[: _COMPLETION_RESULT_MAX_LEN - 3].rstrip() + "..."
        return text
    return None


def consumer_texts_for_current_step(session, latest_user_message: Optional[Message] = None) -> List[str]:
    """Consumer messages since the previous step completed (newest first)."""
    last_complete_at = (
        Message.objects.filter(session=session, is_step_complete=True)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    qs = Message.objects.filter(
        session=session,
        sender__consumer__isnull=False,
    ).exclude(text="")
    if last_complete_at:
        qs = qs.filter(created_at__gt=last_complete_at)

    texts: List[str] = []
    if latest_user_message and latest_user_message.text:
        texts.append(latest_user_message.text)

    for text in qs.order_by("-created_at").values_list("text", flat=True)[:30]:
        if text not in texts:
            texts.append(text)
    return texts


def coerce_completion_result(
    *,
    completion_result: Optional[str],
    is_step_complete: Optional[bool],
    session,
    user_message: Optional[Message] = None,
) -> Optional[str]:
    """Keep a real captured answer; if the model dumped N/A / Yes, recover it from the step."""
    if not is_step_complete:
        return None

    text = (completion_result or "").strip() or None
    if text == SKIP_COMPLETION_RESULT:
        return SKIP_COMPLETION_RESULT
    if is_usable_completion_result(text):
        return text

    return pick_completion_result_from_texts(
        consumer_texts_for_current_step(session, user_message)
    )


def update_summary(summary, date=None, freezer=None):
    """
    Updates the summary with yesterday's messages using AI,
    and stores the log in S3.
    """
    if not date:
        date = timezone.now().date() - timedelta(days=1)

    consumer = summary.consumer
    exercise = summary.exercise if hasattr(summary, "exercise") else None

    sessions_data = Session.get_with_messages(date=date, consumer=consumer, exercise=exercise)

    all_lines = []

    user_first_name = consumer.user.first_name

    for i, session_data in enumerate(sessions_data):

        session_id = session_data["session"]
        session = Session.objects.get(id=session_id)

        if freezer is not None:
            freezer.stop()

        _append_messages_to_log(
            session=session,
            session_no=i + 1,
            user=consumer.user,
            messages=session_data["messages"],
            date=date
        )
        if freezer is not None:
            freezer.start()

        session_message_data = _format_session(
            session=session,
            user_first_name=user_first_name,
            messages=session_data["messages"]
        )

        all_lines.extend(session_message_data)

        session_ai_prompt = build_session_prompt(session_message_data, summary, user_first_name)
        update_session(session_ai_prompt, session)

    sessions = "\n".join(all_lines)

    exercise_prompt_text = ""
    if exercise:
        exercise_prompt_text = f"""
            <EXERCISE>
                <TITLE>{exercise.title}</TITLE>
                <SUBTITLE>{exercise.subtitle}</SUBTITLE>
                <DESCRIPTION>{exercise.description}</TITLE>
                <STEPS>{_get_formatted_exercise_steps_text(exercise)}</TITLE>
            </EXERCISE>
        """

    ai_prompt = f"""
        You are a helpful assistant training in the Unified Protocol that keeps detailed notes and observations
        about your client {user_first_name}.
         
        Your task is to update your existing summary and observations for {user_first_name} while factoring in the most 
        recent sessions you have had.

        <NEW_SESSIONS>
            {sessions}
        </NEW_SESSIONS>

        <PREVIOUS_SUMMARY>
            {summary.detailed or ''}
        </PREVIOUS_SUMMARY>

        <PREVIOUS_OBSERVATIONS>
            {summary.observations or ''}
        </PREVIOUS_OBSERVATIONS>
        
        <PREVIOUS_NEXT_STEPS>
            {summary.next_steps or ''}
        </PREVIOUS_NEXT_STEPS>
        
        {exercise_prompt_text}

        Update the detailed notes and observations based on the new conversation.
        
        Observations are detailed notes on what exercises the user has completed, whether or not they enjoy doing the exercise
        along with any insights into the state of mind / any other relevant clinical observations.
        
        """

    ai_response = AI.ask(prompt=ai_prompt, schema=SUMMARY_RESPONSE_SCHEMA)

    try:
        summary.detailed = ai_response.get("detailed", summary.detailed)
        summary.observations = ai_response.get("observations", summary.observations)
        summary.next_steps = ai_response.get("next_steps", summary.next_steps)

    except json.JSONDecodeError:
        # If AI doesn't return JSON, treat as plain text notes update
        summary.detailed = ai_response

    summary.save()


def get_response(session: Session, consumer_message: Message) -> (GeneralResponse | ExerciseResponse, dict, Asset | None, Exercise | None):
    """Entry point: get the agent's response to a user's message."""
    consumer = consumer_message.sender.consumer
    assert consumer, "Message sender must be a consumer"

    prompt = _prepare_prompt(session=session)

    schema = ExerciseResponse if session.exercise else GeneralResponse

    model_name = consumer.agent.model

    dependencies = Dependencies(
        session=session,
        consumer=consumer,
        exercise=session.exercise,
    )

    timer_start = time.perf_counter()
    usage = {}

    def _run(provider):
        pydantic_model, model_settings = build_pydantic_model(provider, model_name)
        agent_kwargs = {
            "deps_type": Dependencies,
            "output_type": schema,
            "system_prompt": prompt,
        }
        if model_settings is not None:
            agent_kwargs["model_settings"] = model_settings

        agent: Agent[Dependencies, BaseModel] = Agent(pydantic_model, **agent_kwargs)
        _register_tools(agent)

        result = agent.run_sync(
            user_prompt=consumer_message.text,
            deps=dependencies,
            message_history=session.get_chat_history(),
            usage_limits=UsageLimits(tool_calls_limit=2)
        )
        return result

    try:
        result, _provider = run_with_failover(_run, model_name=model_name)
        usage = result.usage().__dict__
        response_data = result.output
        timer_end = time.perf_counter()
        session.update_chat_history(result)

    except Exception as e:
        timer_end = time.perf_counter()
        logger.exception(
            "Agent.get_response failed for session=%s message=%s",
            getattr(session, "id", None),
            getattr(consumer_message, "id", None),
        )

        response_data = schema(**{
            "text": "Sorry, I had an issue understanding your message, can you repeat it or rephrase it for me please?",
            "suggested_responses": [],
            "reasoning": str(e),
            **({} if schema is GeneralResponse else {
                "step_no": session.current_step_no,
                "is_step_complete": False,
                "completion_result": None
            })
        })

    usage = {
        **usage,
        'response_time_in_sec': round(timer_end - timer_start, 3)
    }

    response_data.suggested_responses = sanitize_suggested_responses(
        response_data.suggested_responses,
        response_data.text,
    )

    return response_data, usage, dependencies.asset, dependencies.matched_exercise


def _register_tools(agent: Agent[Dependencies, BaseModel]) -> None:
    @agent.tool
    def get_asset(ctx: RunContext[Dependencies], step_no: int) -> str | dict:
        """Get an image, video, podcast or article, aka 'asset' to show to the user.

        Args:
            step_no: Current step of th exercise
        """

        exercise = ctx.deps.exercise
        if not exercise:
            return {
                "status": "invalid_session",
                "message": "Can't show assets for this session type"
            }

        step = exercise.steps.filter(order=step_no - 1).first()

        if not step:
            return {
                "status": "no_step",
                "message": f"Failed to get asset as couldn't determine the step"
            }

        tags = step.tags.all()
        assets = Asset.objects.all()
        if tags:
            assets = assets.filter(tags__in=tags).distinct()

        # Avoid ORDER BY random() (full sort). Sample from a capped id list.
        asset_ids = list(assets.values_list("id", flat=True)[:200])
        asset = None
        if asset_ids:
            asset = Asset.objects.filter(id=random.choice(asset_ids)).first()

        ctx.deps.asset = asset

        if asset:
            return {
                "status": "ok",
                "asset_id": asset.id,
                "asset": {
                    "id": asset.id,
                    "context": asset.context
                }
            }

        return {
            "status": "not_found",
            "message": "Sorry, I couldn't find an appropriate asset for this exercise"
        }

    @agent.tool
    def get_exercise(ctx: RunContext[Dependencies], exercise_id: str) -> str | dict:
        """Get an exercise to show to the user.

        Args:
            exercise_id: ID of  the exercise
        """
        exercise = Exercise.objects.filter(id=exercise_id, status=Constants.EXERCISE_STATUS_PUBLISHED).first()

        if exercise:
            ctx.deps.matched_exercise = exercise

            return {
                "status": "ok",
                "exercise_id": exercise.id,
                "exercise": {
                    "id": exercise.id,
                    "context": exercise.description
                }
            }

        return {
            "status": "not_found",
            "message": "Sorry, I couldn't find an appropriate exercise"
        }


def _format_knowledge(consumer: Consumer) -> str:
    """Structured User Knowledge Engine summary for session prompts."""
    from ..knowledge.services import get_current_knowledge_summary

    return get_current_knowledge_summary(consumer, include_sensitive=True)


def _format_summary(consumer: Consumer) -> str:
    from ..summary.models import Summary
    """
    Returns the summarized past conversation history for the consumer,
    using the 'Summary' model's stored detailed notes and observations,
    plus the current structured knowledge profile.
    """
    knowledge = _format_knowledge(consumer)

    no_previous_conversations = "No previous conversations exist with this user."
    try:
        summary = Summary.objects.get(consumer=consumer)
    except Summary.DoesNotExist:
        return f"{no_previous_conversations}\n\n{knowledge}"

    if not summary.detailed:
        return f"{no_previous_conversations}\n\n{knowledge}"

    detailed_notes = summary.detailed
    observations = summary.observations or ""

    result = "Detailed notes:\n"
    result += detailed_notes.strip() + "\n\n"

    result += "Observations:\n"
    result += observations.strip() + "\n\n"

    result += knowledge + "\n\n"

    return result


def _append_messages_to_log(user, messages, date, session, session_no):
    """
    Append today's chat messages to the user's log in S3.
    Delegates to the S3 helper for storage.
    """
    if not messages:
        return

    lines = []
    user_first_name = user.first_name
    session_type = session.exercise.title if session.exercise else "General"

    lines += [f"\n\n{date:{PROMPT_DATE_FORMAT}: Session #{session_no} - {session_type}}"]
    for message in messages:
        if message.sender.consumer_id:
            lines += [f"\t\t{user_first_name}: {message.text}"]
        else:
            lines += [f"\t\tYOU: {message.text}"]

    lines += ["\n\n"]

    user_id = user.id
    # One object per session/day — single PUT, no full-history rewrite.
    key = f"consumers/{user_id}/chat_log/{date:%Y-%m-%d}/{session.id}.txt"

    S3Utils.write_log_chunk(key=key, lines=lines)


def _format_session(session, user_first_name, messages):
    lines = []
    session_type = session.exercise.title if session.exercise else "General"

    lines += [f"<Session>"]
    lines += [f"    <Type>{session_type}</Type>"]

    lines += [f"    <Messages>"]
    for message in messages:
        if message.sender.consumer_id:
            lines += [f"        {user_first_name}: {message.text}"]
        else:
            lines += [f"        YOU: {message.text}"]
    lines += [f"    </Messages>"]
    lines += [f"</Session>"]

    return lines


def build_session_prompt(session_message_data, summary, user_first_name):

    session_ai_prompt = f"""
        You are a helpful assistant training in the Unified Protocol that keeps detailed notes and observations
        about your client {user_first_name}.

        Your task is to update your existing sessions data for {user_first_name} while factoring in the most 
        recent session you have had.

        {session_message_data}

        <Summary>
            {summary.detailed or ''}
        </Summary>

        <Observations>
            {summary.observations or ''}
        </Observations>

       Now, Add:
        - "subject": condense the session into 10 or fewer words that describe or summarise the overall subject of the session.
            Important: Do NOT include the user's name, pronouns, or the word "client". 
            Make it neutral (e.g., "Generalized worry and use of distraction").
        - "rating": critically grade your own helpfulness on a scale of 0.00 to 10.00
        - "rating_reason": explain briefly why you gave this rating (e.g., "I was able to provide structured guidance but could 
          have asked more reflective questions").
        - "risk_level": classify the user's risk into one of the following categories:
            • low – user is discussing their emotions or general topics
            • moderate – user has hinted towards possible self-harm or may be prone to self-harm or harming others
            • high – user has explicitly expressed desire to self-harm or harm others
            • critical – user has stated concrete plans to self-harm or harm others

            """

    return session_ai_prompt


def update_session(session_ai_prompt, session):
    session_ai_response = AI.ask(prompt=session_ai_prompt, schema=SESSION_RESPONSE_SCHEMA)

    try:
        session.subject = session_ai_response.get("subject", session.subject)
        session.rating = session_ai_response.get("rating", session.rating)
        session.rating_reason = session_ai_response.get("rating_reason", session.rating_reason)
        session.risk_level = session_ai_response.get("risk_level", session.risk_level)

        total_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            
            "response_time_in_sec": 0,

            "total_token_count": 0,
            "prompt_token_count": 0,
            "thoughts_token_count": 0,
            "candidates_token_count": 0,
            "cached_content_token_count": 0,
            "tool_use_prompt_token_count": 0,
        }

        for message in session.messages.filter(usage__isnull=False):
            for key, value in total_usage.items():
                message_value = message.usage.get("key", 0)
                if message_value:
                    total_usage[key] = value + message_value

        session.usage = total_usage
        session.save()
    except json.JSONDecodeError:
        traceback.format_exc()


def _prepare_prompt(session: Session) -> str:

    cached = session.cached_prompt
    if cached:
        # Older general-chat prompts told Toni to "click the exercise".
        # Rebuild so today's session asks Yes / No instead.
        if session.exercise_id or "click the exercise" not in cached:
            return cached
        session.cached_prompt = None

    consumer = session.consumer
    today_date_str = DateUtils.today().strftime(PROMPT_DATE_FORMAT)
    notes = _format_summary(consumer)

    template = _prompt_template(session)

    exercise_extra = {}
    exercise = session.exercise

    if exercise:
        exercise_summary = ExerciseSummary.get_or_create(consumer, exercise)

        if session.in_pre_exercise_phase():
            from ..exercise.pre_exercise import format_pre_exercise_prompt_block

            exercise_extra = {
                "exercise_id": exercise.id,
                "exercise_steps": (
                    "Pre-exercise check-in is active. Do not run exercise steps yet."
                ),
                "exercise_steps_no": exercise.steps_no,
                "exercise_name": exercise.title,
                "exercise_description": exercise.description,
                "exercise_summary_notes": exercise_summary.detailed,
                "pre_exercise_block": format_pre_exercise_prompt_block(
                    exercise, consumer
                ),
            }
        else:
            exercise_steps = _get_formatted_exercise_steps_text(exercise)
            exercise_extra = {
                "exercise_id": exercise.id,
                "exercise_steps": exercise_steps,
                "exercise_steps_no": exercise.steps_no,
                "exercise_name": exercise.title,
                "exercise_description": exercise.description,
                "exercise_summary_notes": exercise_summary.detailed,
                "pre_exercise_block": "",
            }
    else:
        exercise_extra["exercises"] = _published_exercises_prompt_block()

    prompt = template.format(
        notes=notes,
        today_date=today_date_str,
        goals=Setting.get_general_prompt(),
        user_name=consumer.user.first_name,
        therapeutic_instructions=Setting.get_therapeutic_prompt(),
        programming_instructions=Constants.PROMPT_PROGRAMMING_INSTRUCTIONS,
        **exercise_extra,
    )

    session.cached_prompt = prompt
    session.save(update_fields=["cached_prompt"])

    return prompt


def _prompt_template(session) -> str:
    filename = 'general_prompt.txt' if not session.exercise else "exercise_prompt.txt"
    path = os.path.join(STATIC_FILES_DIR, filename)
    with open(path, 'r') as f:
        return f.read()


def _get_formatted_exercise_steps_text(exercise):
    steps_no = exercise.steps.count()
    steps = ""
    for i, step in enumerate(exercise.steps.order_by("order")):
        completion_criteria = step.completion_criteria
        if i < steps_no - 1:
            completion_criteria += (
                "\n\nYou also must also have:"
                " - Explicitly asked the user if they are ready to move onto the next step"
                " - Received a confirmation from the user to progress to the next step"
            )
        steps += Constants.PROMPT_STEP.format(
            step_title=step.title,
            step_description=step.description,
            step_instructions=step.instructions,
            step_completion_criteria=completion_criteria,
            step_completion_prompt=step.completion_prompt
        )
    return steps


_PUBLISHED_EXERCISES_CACHE_KEY = "prompt:published_exercises_v1"
_PUBLISHED_EXERCISES_CACHE_TTL = 300


def _published_exercises_prompt_block() -> str:
    """Cached catalog of published exercises for the general-chat system prompt."""
    from django.core.cache import cache

    cached = cache.get(_PUBLISHED_EXERCISES_CACHE_KEY)
    if cached is not None:
        return cached

    exercises = ""
    for exercise in Exercise.objects.filter(status=Constants.EXERCISE_STATUS_PUBLISHED).only(
        "id", "title", "subtitle", "description"
    ):
        exercises += f"""
                <EXERCISE>
                    <ID>{exercise.id}</ID>
                    <TITLE>{exercise.title}</TITLE>
                    <SUBTITLE>{exercise.subtitle}</SUBTITLE>
                    <DESCRIPTION>{exercise.description}</TITLE>
                </EXERCISE>"""

    cache.set(_PUBLISHED_EXERCISES_CACHE_KEY, exercises, _PUBLISHED_EXERCISES_CACHE_TTL)
    return exercises


def invalidate_published_exercises_cache():
    from django.core.cache import cache
    cache.delete(_PUBLISHED_EXERCISES_CACHE_KEY)

