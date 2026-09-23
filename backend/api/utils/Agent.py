import json
import logging
import os
import random
import time
import traceback
from datetime import timedelta
from typing import Optional, List

from dataclasses import dataclass

from django.utils import timezone
from pydantic import BaseModel, Field, field_validator

from pydantic_ai import Agent, RunContext, UsageLimits

from .AI import AI, SessionAiResponse, SummaryAiResponse
from .AiProviderFactory import build_pydantic_model, run_with_failover

from ..asset.models import Asset
from ..consumer.models import Consumer
from ..message.models import Message
from ..exercise_summary.models import Exercise, ExerciseSummary
from ..session.serializers import Session, SessionDetailSerializer

from ..utils import DateUtils, Constants, S3 as S3Utils
from .SuggestedResponses import sanitize_suggested_responses
from .completion import is_usable_completion_result, pick_completion_result_from_texts

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
      description="""Required. A text based response to your client's question. Speak to the client in second person. Never write facilitator notes, status lines, or third-person copy such as 'User ready for Step 3' or 'the user has…'.""",
    )
    risk_level: str = Field(
        default="none",
        description="One of none, low, moderate, high. none when there is no safety concern.",
    )
    question_kind: str = Field(
        default="none",
        description=(
            "open when your message ends with a question inviting the user to describe "
            "something in their own words; closed when it invites a yes/no or a choice; "
            "readiness when it is the readiness question; none when there is no question."
        ),
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

    @field_validator("suggested_responses", mode="before")
    @classmethod
    def _coerce_chips(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [value]
        return value


class ExerciseStateResponse(GeneralResponse):
    """Exercise schema used when the state machine flag is on."""

    step_goal_met: bool = Field(
        default=False,
        description=(
            "True when this step's work is done: the concrete elements named in done_when "
            "are present in the user's own words."
        ),
    )
    asks_readiness: bool = Field(
        default=False,
        description=(
            "True only when the step's work is done and this message is a single question "
            "asking whether they are ready to continue. Never true in the same message as "
            "other questions."
        ),
    )

    @field_validator("step_goal_met", "asks_readiness", mode="before")
    @classmethod
    def _coerce_flag(cls, value):
        if isinstance(value, bool) or value is None:
            return bool(value)
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"true", "yes", "y", "1"}


class ExerciseResponse(GeneralResponse):
    is_step_complete: bool = Field(
        ...,
        description=(
            "Required. True only after this step's work is done AND the user has confirmed a "
            "dedicated readiness ask ('ready to progress to the next step?' or, on the last "
            "catalogue step, 'ready to see your summary?'). Never true in the same turn as "
            "that ask. Never true just because you incremented step_no. Never true as a "
            "goodbye or time-of-day sign-off. 'Move on' / 'ready to proceed' inside the step "
            "instructions means continue THIS step."
        )
    )
    step_no: int = Field(
        ...,
        description="Required. The current step number (1-based). Stay on the live step until is_step_complete is true."
    )
    completion_result: Optional[str] = Field(
        description=(
            "Required when is_step_complete is true. The user's captured answer for this "
            "step (what COMPLETION_PROMPT asked them to produce), in their own words. "
            "Quote the substance from earlier in the step if the latest message is only "
            "yes/ok to proceed. Never N/A, None, unknown, status notes like "
            "'User ready for Step 3', or third-person facilitator copy about 'the user'."
        )
    )


SKIP_COMPLETION_RESULT = "Step Skipped"


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

    from django.conf import settings as django_settings

    if session.exercise and django_settings.AI_STATE_MACHINE_ENABLED:
        schema = ExerciseStateResponse
    else:
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
        _register_tools(agent, session)

        from .history import build_history
        from .turn_hint import user_prompt_with_hint

        result = agent.run_sync(
            user_prompt=user_prompt_with_hint(session, consumer_message),
            deps=dependencies,
            message_history=build_history(
                session, exclude_message_id=getattr(consumer_message, "id", None)
            ),
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
            **({} if "is_step_complete" not in schema.model_fields else {
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


_PROGRESSION_START = (
    "        - Do not allow the user to do anything outside of this exercise."
)
_STATE_MACHINE_PROGRESSION = (
    "        - Set asks_readiness only when the step's work is done, and make that "
    "message a single question.\n"
    "        - Do not complete the step yourself. The app shows the readiness chips.\n"
)


def _state_machine_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "AI_STATE_MACHINE_ENABLED", False))


def _state_machine_progression(prompt: str) -> str:
    start = prompt.find(_PROGRESSION_START)
    end = prompt.find("    </PROGRAMMING_INSTRUCTIONS>")
    if start == -1 or end == -1 or end < start:
        return prompt
    return prompt[:start] + _STATE_MACHINE_PROGRESSION + prompt[end:]


def _register_tools(agent: Agent[Dependencies, BaseModel], session=None) -> None:
    # get_exercise is the general-chat catalogue tool. Inside an exercise,
    # including check-in, calling it makes Gemini fail the structured turn.
    # get_asset is only useful once a real step is underway.
    in_exercise = bool(session and session.exercise_id)
    in_check_in = bool(session and session.in_pre_exercise_phase())
    if _state_machine_enabled():
        if in_exercise and not in_check_in:
            _register_get_asset(agent)
        if not in_exercise:
            _register_get_exercise(agent)
        return

    _register_get_asset(agent)
    _register_get_exercise(agent)


def _register_get_exercise(agent: Agent[Dependencies, BaseModel]) -> None:
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


def _register_get_asset(agent: Agent[Dependencies, BaseModel]) -> None:
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


def _format_summary(consumer: Consumer) -> str:
    """Client summary notes only. Knowledge is a separate prompt block."""
    from .prompt_blocks import render_client_summary

    return render_client_summary(consumer)


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
    prompt_phase = _prompt_phase(session)
    meta = dict(session.cached_prompt_meta or {})
    if cached:
        # Older prompts left {today_date} uninterpolated (nested format),
        # told Toni to "click the exercise", or predate the block order.
        # A check-in prompt must not be reused once Start has moved to step 1.
        stale_placeholders = "{today_date}" in cached or "{current_time}" in cached
        stale_click = not session.exercise_id and "click the exercise" in cached
        stale_shape = "<SESSION_CONTEXT>" not in cached
        stale_phase = meta.get("prompt_phase") != prompt_phase
        stale_machine = meta.get("state_machine") != _state_machine_enabled()
        if not any((stale_placeholders, stale_click, stale_shape, stale_phase, stale_machine)):
            return cached
        session.cached_prompt = None

    from .prompt_blocks import (
        build_token_context,
        prompt_bodies_for_session,
        render_client_summary,
        render_exercise_catalogue,
        render_form_answers,
        render_knowledge,
        render_session_context,
        resolve_tokens,
    )

    consumer = session.consumer
    now_local = DateUtils.local_now()
    today_date_str = now_local.strftime(PROMPT_DATE_FORMAT)
    current_time_str = now_local.strftime("%H:%M")
    notes = render_client_summary(consumer)
    bodies = prompt_bodies_for_session(session)
    token_context = build_token_context(consumer, session.exercise, session)

    template = _prompt_template(session)

    exercise_extra = {}
    exercise = session.exercise

    if exercise:
        exercise_summary = ExerciseSummary.get_or_create(consumer, exercise)
        live_steps_no = exercise.steps.count() or exercise.steps_no
        reference = resolve_tokens(exercise.reference_material or "", token_context)
        description = resolve_tokens(exercise.description or "", token_context)

        if session.in_pre_exercise_phase():
            from ..exercise.pre_exercise import format_pre_exercise_prompt_block

            exercise_extra = {
                "exercise_id": exercise.id,
                "exercise_steps": (
                    "Pre-exercise check-in is active. Do not run exercise steps yet."
                ),
                "exercise_steps_no": live_steps_no,
                "exercise_name": exercise.title,
                "exercise_description": description,
                "exercise_reference": reference,
                "exercise_summary_notes": exercise_summary.detailed or "",
                "form_answers": render_form_answers(session),
                "pre_exercise_block": format_pre_exercise_prompt_block(
                    exercise, consumer, session=session
                ),
            }
        else:
            only_index = None
            if _state_machine_enabled():
                only_index = max(0, (session.current_step_no or 1) - 1)
                step_no = only_index + 1
                description = (
                    "Clinical background only. Do not read this to the user, "
                    "and do not turn it into a welcome or a suitability check.\n\n"
                    + description
                )
            exercise_steps = _get_formatted_exercise_steps_text(
                exercise, token_context, only_index=only_index
            )
            if _state_machine_enabled():
                exercise_steps = _step_already_started(step_no, live_steps_no) + exercise_steps
            exercise_extra = {
                "exercise_id": exercise.id,
                "exercise_steps": exercise_steps,
                "exercise_steps_no": live_steps_no,
                "exercise_name": exercise.title,
                "exercise_description": description,
                "exercise_reference": reference,
                "exercise_summary_notes": exercise_summary.detailed or "",
                "form_answers": render_form_answers(session),
                "pre_exercise_block": "",
            }
        exercise_extra["session_context"] = render_session_context(consumer, session)
        exercise_extra["knowledge"] = render_knowledge(
            consumer, "check_in" if session.in_pre_exercise_phase() else "exercise", exercise
        )
    else:
        from ..knowledge.followup import format_onboarding_followup_block

        exercise_extra = {
            "exercises": render_exercise_catalogue(),
            "onboarding_followup_block": format_onboarding_followup_block(session),
            "goals": bodies.get(Constants.PROMPT_KEY_GOALS, ""),
            "triage": bodies.get(Constants.PROMPT_KEY_TRIAGE, ""),
            "session_context": render_session_context(consumer, session),
            "knowledge": render_knowledge(consumer, "general"),
        }

    user_name = consumer.user.first_name or "there"
    programming_instructions = Constants.PROMPT_PROGRAMMING_INSTRUCTIONS.format(
        user_name=user_name,
    )

    prompt = template.format(
        notes=notes,
        today_date=today_date_str,
        current_time=current_time_str,
        local_timezone=str(DateUtils.PROGRESS_TZ),
        user_name=user_name,
        therapeutic_instructions=bodies.get(Constants.PROMPT_KEY_THERAPEUTIC, ""),
        programming_instructions=programming_instructions,
        **exercise_extra,
    )
    if exercise and _state_machine_enabled():
        prompt = _state_machine_progression(prompt)

    meta = dict(session.cached_prompt_meta or {})
    meta["prompt_phase"] = prompt_phase
    meta["state_machine"] = _state_machine_enabled()
    session.cached_prompt_meta = meta
    session.cached_prompt = prompt
    session.save(
        update_fields=[
            "cached_prompt",
            "cached_prompt_meta",
            "prompt_version",
            "updated_at",
        ]
    )

    return prompt


def _prompt_phase(session) -> str:
    if not session.exercise_id:
        return "general"
    if session.in_pre_exercise_phase():
        return "check_in"
    if _state_machine_enabled():
        return f"step:{session.current_step_no or 1}"
    return "exercise"


def _prompt_template(session) -> str:
    filename = 'general_prompt.txt' if not session.exercise else "exercise_prompt.txt"
    path = os.path.join(STATIC_FILES_DIR, filename)
    with open(path, 'r') as f:
        return f.read()


def _step_already_started(step_no: int, steps_no: int) -> str:
    if step_no <= 1:
        return (
            "The pre-exercise check-in is finished and this exercise has already been introduced. "
            "You are on step 1. Your next message must be the first question in the step instructions below. "
            "Do not write a welcome, a suitability check, a time estimate, or a line about getting started.\n\n"
        )
    return (
        f"You are already on step {step_no} of {steps_no}. "
        "Do not introduce the exercise. Follow only this step's instructions.\n\n"
    )


def _get_formatted_exercise_steps_text(exercise, token_context=None, only_index=None):
    from .prompt_blocks import resolve_tokens

    context = token_context or {}
    steps_no = exercise.steps.count()
    steps = ""
    for i, step in enumerate(exercise.steps.order_by("order")):
        if only_index is not None and i != only_index:
            continue
        completion_criteria = step.done_when if step.done_when else step.completion_criteria
        completion_criteria = resolve_tokens(completion_criteria, context)
        description = resolve_tokens(step.description, context)
        instructions = resolve_tokens(step.instructions, context)
        if _state_machine_enabled():
            if i < steps_no - 1:
                completion_criteria += (
                    "\n\nWhen this step's work is done, set step_goal_met and asks_readiness "
                    "on a message whose only question is whether they are ready for the next step."
                )
            else:
                completion_criteria += (
                    "\n\nWhen this step's work is done, set step_goal_met and asks_readiness "
                    "on a message whose only question is whether they are ready to finish."
                )
        elif i < steps_no - 1:
            completion_criteria += (
                "\n\nAfter this step's work is finished, send a SEPARATE message whose ONLY "
                "question is whether they are ready for the next step "
                '(e.g. "Are you ready to progress to the next step?"). '
                "Do not set is_step_complete in that message. "
                "Only set is_step_complete after they confirm (yes/ok). "
                "'Move on' or 'ready to proceed' in this step's instructions means continue "
                "THIS step — it is not permission to complete it."
            )
        else:
            completion_criteria += (
                "\n\nAfter this step's work is finished, send a SEPARATE message whose ONLY "
                "question is whether they are ready to see their summary "
                '(e.g. "Are you ready to see your summary?"). '
                "Do not set is_step_complete in that message. "
                "Only set is_step_complete after they confirm (yes/ok). "
                "Do not wrap up with goodbye or a time-of-day sign-off "
                "(good morning / good afternoon / good evening / goodnight). "
                "The app shows the summary page after they confirm."
            )
        steps += Constants.PROMPT_STEP.format(
            step_title=step.title,
            step_description=description,
            step_instructions=instructions,
            step_completion_criteria=completion_criteria,
            step_completion_prompt=step.completion_prompt or "",
        )
    return steps


def _published_exercises_prompt_block() -> str:
    """Cached catalog of published exercises for the general-chat system prompt."""
    from .prompt_blocks import render_exercise_catalogue

    return render_exercise_catalogue()


def invalidate_published_exercises_cache():
    from .prompt_blocks import invalidate_published_exercises_cache as _invalidate

    _invalidate()

