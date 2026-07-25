import json
import os
import time
import traceback
from datetime import timedelta
from typing import Optional, List, Type

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from .AI import AI

from ..asset.models import Asset
from ..setting.models import Setting

from ..consumer.models import Consumer
from ..message.models import Message
from ..exercise_summary.models import Exercise, ExerciseSummary
from ..session.serializers import Session, SessionDetailSerializer

from ..utils import DateUtils, Api, Constants, S3 as S3Utils

PROMPT_DATE_FORMAT = "%d %B, %Y"
STATIC_FILES_DIR = 'api/utils/files'
SUMMARY_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "detailed": types.Schema(type=types.Type.STRING,  description="Notes on user"),
        "observations": types.Schema(type=types.Type.STRING, description="Observations intended to be read by user"),
        "next_steps": types.Schema(type=types.Type.STRING,  description="Next steps you deem necessary for user")
    },
    required=["detailed", "observations", "next_steps"]
)

SESSION_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "subject": types.Schema(type=types.Type.STRING),
        "rating": types.Schema(type=types.Type.NUMBER),
        "rating_reason": types.Schema(type=types.Type.STRING),
        "risk_level": types.Schema(
            type=types.Type.STRING,
            enum=["low", "moderate", "high", "critical"]
        )
    },
    required=["subject", "rating", "rating_reason", "risk_level"]
)


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
        description="""Optional. Suggest up to 3 client responses to your message where appropriate, each must be a string between 1 and 4 words."""
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
        description="Optional. If a step has just been completed this should be the result based on the completion prompt for that steps. "
                    "This must be specified if 'is_step_complete' is true"
    )


class AgentConfig(types.GenerateContentConfig):
    thinking_config: Type[BaseModel] = types.ThinkingConfig(thinking_budget=0, include_thoughts=False)
    system_instruction: str = None
    temperature: float = 1
    response_mime_type: str = 'application/json'
    response_schema: Type[BaseModel] = GeneralResponse


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

    # Minimize latency: disable/limit "thinking". Gemini 3.x models support
    # thinking_level (they think by default, adding 10s+ per reply); 2.x models
    # reject thinking_level and require thinking_budget instead.
    if model_name.startswith(("gemini-3", "gemini-4")):
        thinking_config = {"thinking_level": "minimal"}
    else:
        thinking_config = {"thinking_budget": 0, "include_thoughts": False}

    # Explicit HTTP timeout so a slow/unreachable Gemini API can't hang this
    # request forever — without it, one bad call permanently occupies a
    # Gunicorn worker (surfaces as HTTP 499s on unrelated endpoints once
    # every worker gets stuck this way).
    genai_client = genai.Client(
        api_key=Api.GOOGLE_API_KEY,
        http_options=types.HttpOptions(timeout=settings.GEMINI_HTTP_TIMEOUT_MS),
    )

    agent: Agent[Dependencies, BaseModel] = Agent(
        GoogleModel(
            model_name=model_name,
            provider=GoogleProvider(client=genai_client),
        ),
        deps_type=Dependencies,
        output_type=schema,
        system_prompt=prompt,
        model_settings=GoogleModelSettings(google_thinking_config=thinking_config),
    )

    dependencies = Dependencies(
        session=session,
        consumer=consumer,
        exercise=session.exercise,
    )

    _register_tools(agent)

    timer_start = time.perf_counter()
    usage = {}

    try:
        result = agent.run_sync(
            user_prompt=consumer_message.text,
            deps=dependencies,
            message_history=session.get_chat_history(),
            usage_limits=UsageLimits(tool_calls_limit=2)
        )

        usage = result.usage().__dict__
        response_data = result.output
        timer_end = time.perf_counter()

        session.update_chat_history(result)

    except Exception as e:
        timer_end = time.perf_counter()

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
        assets = Asset.objects.filter()
        if tags:
            assets = assets.filter(tags__in=tags)

        asset = assets.order_by('?').first()

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


def _format_summary(consumer: Consumer) -> str:
    from ..summary.models import Summary
    """
    Returns the summarized past conversation history for the consumer,
    using the 'Summary' model's stored detailed notes and observations.
    """
    no_previous_conversations = "No previous conversations exist with this user."
    try:
        summary = Summary.objects.get(consumer=consumer)
    except Summary.DoesNotExist:
        return no_previous_conversations

    if not summary.detailed:
        return no_previous_conversations

    detailed_notes = summary.detailed
    observations = summary.observations or ""

    result = "Detailed notes:\n"
    result += detailed_notes.strip() + "\n\n"

    result += "Observations:\n"
    result += observations.strip() + "\n\n"

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
    key = f"consumers/{user_id}/chat_log.txt"

    S3Utils.append_to_txt_file(key=key, lines=lines)


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

    if session.cached_prompt:
        return session.cached_prompt

    consumer = session.consumer
    today_date_str = DateUtils.today().strftime(PROMPT_DATE_FORMAT)
    notes = _format_summary(consumer)

    template = _prompt_template(session)

    exercise_extra = {}
    exercise = session.exercise

    if exercise:
        exercise_steps = _get_formatted_exercise_steps_text(exercise)

        exercise_summary = ExerciseSummary.get_or_create(consumer, exercise)

        exercise_extra = {
            "exercise_id": exercise.id,
            "exercise_steps": exercise_steps,
            "exercise_steps_no": exercise.steps_no,
            "exercise_name": exercise.title,
            "exercise_description": exercise.description,
            "exercise_summary_notes": exercise_summary.detailed,
        }
    else:
        exercises = ""
        for exercise in Exercise.objects.filter(status=Constants.EXERCISE_STATUS_PUBLISHED):
            exercises += f"""
                <EXERCISE>
                    <ID>{exercise.id}</ID>
                    <TITLE>{exercise.title}</TITLE>
                    <SUBTITLE>{exercise.subtitle}</SUBTITLE>
                    <DESCRIPTION>{exercise.description}</TITLE>
                </EXERCISE>"""

        exercise_extra["exercises"] = exercises

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

