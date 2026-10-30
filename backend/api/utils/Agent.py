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
from .reply_style import normalise_reply, reply_ends_mid_sentence, reply_leaves_the_step
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
      description=(
          "Required. A text based response to your client's question. Speak to the client in second person. "
          "Never write facilitator notes, status lines, or third-person copy such as 'User ready for Step 3' or 'the user has…'. "
          "Never use the double-quote character in this text. When repeating the client's words, use single quotes or no quotes. "
          "Always finish the sentence with a full stop or question mark. "
          "Never open with 'Thanks for sharing', 'Thank you for', or 'It sounds like'."
      ),
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
            "Optional. Up to 3 tap-to-send replies in the client's own voice, each 1-4 words. "
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
        session.session_steps.filter(completed=True)
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
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


_SUMMARY_SHRINK_MIN_LENGTH = 300
_SUMMARY_SHRINK_MAX_RATIO = 0.5


def _summary_field_or_keep(stored, returned, *, consumer_id, field_name):
    """Keep a long stored field when the reply is under half its length."""
    previous = (stored or "").strip()
    new = (returned if returned is not None else "").strip()
    if (
        len(previous) >= _SUMMARY_SHRINK_MIN_LENGTH
        and len(new) < _SUMMARY_SHRINK_MAX_RATIO * len(previous)
    ):
        logger.warning(
            "Refused summary shrink consumer_id=%s field=%s previous_len=%s new_len=%s",
            consumer_id,
            field_name,
            len(previous),
            len(new),
        )
        return stored
    return returned


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

    sessions = "\n".join(all_lines)

    from .summary_prompts import client_summary_prompt
    from ..setting.models import Setting

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

    ai_prompt = client_summary_prompt(
        Setting.get_update_summary(),
        user_first_name,
        sessions,
        summary.detailed,
        summary.observations,
        summary.next_steps,
        exercise_prompt_text,
    )

    ai_response = AI.ask(prompt=ai_prompt, schema=SUMMARY_RESPONSE_SCHEMA)

    from .user_grounding import keep_grounded_prose, user_text_from_messages

    user_blob = "\n".join(
        user_text_from_messages(session_data["messages"]) for session_data in sessions_data
    )
    try:
        summary.detailed = _summary_field_or_keep(
            summary.detailed,
            ai_response.get("detailed", summary.detailed),
            consumer_id=summary.consumer_id,
            field_name="detailed",
        )
        summary.observations = _summary_field_or_keep(
            summary.observations,
            ai_response.get("observations", summary.observations),
            consumer_id=summary.consumer_id,
            field_name="observations",
        )
        summary.next_steps = _summary_field_or_keep(
            summary.next_steps,
            ai_response.get("next_steps", summary.next_steps),
            consumer_id=summary.consumer_id,
            field_name="next_steps",
        )

    except json.JSONDecodeError:
        # If AI doesn't return JSON, treat as plain text notes update
        summary.detailed = _grounded_or_previous(
            ai_response if isinstance(ai_response, str) else "",
            summary.detailed,
            user_blob,
            keep_grounded_prose,
        )

    summary.save()


def _grounded_or_previous(candidate, previous, user_blob, keep) -> str:
    grounded = keep(candidate, user_blob)
    if grounded:
        return grounded
    return previous or ""


# A non-last step must not be closed as if the exercise were over.
# "for today" / "for now" count only inside a readiness question.
_OFFERS_TO_END = re.compile(
    r"\bready to finish\b"
    r"|\bready to wrap up\b"
    r"|\bwrap(?:ping)? up (?:this|the|our) (?:exercise|session)\b"
    r"|\bwrapping up\b"
    r"|\bfinish (?:this|the|our) (?:exercise|session)\b"
    r"|\bconclude (?:this|the|our)\b"
    r"|\bfinal (?:part|stage) of (?:this|the|our) exercise\b"
    r"|[^.!?\n]*\b(?:ready|shall we|should we|wrap up|finish|stop|end|leave|conclude|pause)\b"
    r"[^.!?\n]*\bfor (?:today|now)\b[^.!?\n]*\?"
    r"|[^.!?\n]*\bfor (?:today|now)\b[^.!?\n]*"
    r"\b(?:ready|shall we|should we|wrap up|finish|stop|end|leave|conclude|pause)\b"
    r"[^.!?\n]*\?",
    re.IGNORECASE,
)


def _reply_offers_to_end_the_exercise(text: str | None) -> bool:
    return bool(_OFFERS_TO_END.search(text or ""))


def _hold_on_step(response_data) -> None:
    """Replace an off-script reply so the user is not offered another technique."""
    from .turn_hint import ON_STEP_FALLBACK

    response_data.text = ON_STEP_FALLBACK
    response_data.suggested_responses = []
    response_data.question_kind = Constants.QUESTION_KIND_OPEN
    if hasattr(response_data, "asks_readiness"):
        response_data.asks_readiness = False
    if hasattr(response_data, "step_goal_met"):
        response_data.step_goal_met = False
    if hasattr(response_data, "is_step_complete"):
        response_data.is_step_complete = False


def _current_step_instructions(session) -> str | None:
    """Title, instructions, and reference for the live step.

    None outside an exercise step. A technique named in any of those may be
    used. One named only in the model's own reply may not.
    """
    if not getattr(session, "exercise_id", None):
        return None
    if session.in_pre_exercise_phase():
        return None
    order = (session.current_step_no or 1) - 1
    row = (
        session.session_steps.filter(order=order).select_related("step").first()
    )
    if row is None or row.step is None:
        return None
    step = row.step
    parts = (
        step.title or "",
        step.instructions or "",
        getattr(step, "reference_material", None) or "",
    )
    return "\n".join(part.strip() for part in parts if part and part.strip())


def get_response(session: Session, consumer_message: Message) -> (GeneralResponse | ExerciseResponse, dict, Asset | None, Exercise | None):
    """Entry point: get the agent's response to a user's message."""
    from .prompt_debug import capture_on, remember_reply, remember_turn

    consumer = consumer_message.sender.consumer
    assert consumer, "Message sender must be a consumer"

    prompt = _prepare_prompt(session=session)

    if session.exercise:
        schema = ExerciseStateResponse
    else:
        schema = GeneralResponse

    dependencies = Dependencies(
        session=session,
        consumer=consumer,
        exercise=session.exercise,
    )

    timer_start = time.perf_counter()
    usage = {}

    steer = [None]
    sent_for_result = {}
    result = None
    debug_result = None
    on_step_retried = False
    on_step_held = False

    def _run(provider):
        pydantic_model, model_settings = build_pydantic_model(provider)
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
        from ..grounding.retrieval import augment_user_prompt
        from ..message.turn_prompt import stash_turn_prompt

        user_prompt = augment_user_prompt(
            session,
            consumer_message,
            user_prompt_with_hint(session, consumer_message),
        )
        if steer[0]:
            user_prompt = f"{user_prompt}\n\n<TURN_HINT>\n{steer[0]}\n</TURN_HINT>"
        history = build_history(
            session, exclude_message_id=getattr(consumer_message, "id", None)
        )
        stash_turn_prompt(
            session,
            model_name=getattr(provider, "_resolved_model_name", "")
            or getattr(provider, "default_model", ""),
            system_prompt=prompt,
            user_prompt=user_prompt,
            history=history,
        )
        result = agent.run_sync(
            user_prompt=user_prompt,
            deps=dependencies,
            message_history=history,
            usage_limits=UsageLimits(tool_calls_limit=2)
        )
        if capture_on():
            from ..grounding.retrieval import session_retrieval_enabled

            sent_for_result[id(result)] = {
                "system_prompt": prompt,
                "user_prompt": user_prompt,
                "model_name": getattr(provider, "default_model", None)
                or getattr(provider, "_resolved_model_name", None),
                "retrieval_enabled": session_retrieval_enabled(session),
                "pending": [
                    {"source_id": item.get("source_id")}
                    for item in (getattr(session, "_pending_retrieval", None) or [])
                ],
                "schema": schema,
            }
        return result

    try:
        result, _provider = run_with_failover(_run)
        response_data = result.output
        debug_result = result
        if reply_ends_mid_sentence(getattr(response_data, "text", None)):
            logger.warning(
                "reply ended mid-sentence for session=%s message=%s; retrying once",
                getattr(session, "id", None),
                getattr(consumer_message, "id", None),
            )
            try:
                retry, _provider = run_with_failover(_run)
                retry_data = retry.output
                if not reply_ends_mid_sentence(getattr(retry_data, "text", None)):
                    result = retry
                    response_data = retry_data
                    debug_result = retry
            except Exception:
                logger.exception(
                    "mid-sentence retry failed for session=%s message=%s",
                    getattr(session, "id", None),
                    getattr(consumer_message, "id", None),
                )
        instructions = _current_step_instructions(session)
        reply_text = getattr(response_data, "text", None)
        left = instructions is not None and reply_leaves_the_step(reply_text, instructions)
        from .SessionStateMachine import _is_last_step

        ending = (
            instructions is not None
            and not _is_last_step(session)
            and _reply_offers_to_end_the_exercise(reply_text)
        )
        if left or ending:
            from .turn_hint import NOT_THE_LAST_STEP_HINT, STAY_ON_STEP_HINT

            logger.warning(
                "reply left the live step for session=%s message=%s; retrying once",
                getattr(session, "id", None),
                getattr(consumer_message, "id", None),
            )
            steer[0] = NOT_THE_LAST_STEP_HINT if ending else STAY_ON_STEP_HINT
            stayed = False
            try:
                retry, _provider = run_with_failover(_run)
                on_step_retried = True
                debug_result = retry
                retry_data = retry.output
                retry_text = getattr(retry_data, "text", None)
                if ending:
                    result = retry
                    response_data = retry_data
                    stayed = True
                elif not reply_leaves_the_step(retry_text, instructions):
                    result = retry
                    response_data = retry_data
                    stayed = True
                else:
                    logger.warning(
                        "on-step retry still left the step for session=%s message=%s",
                        getattr(session, "id", None),
                        getattr(consumer_message, "id", None),
                    )
            except Exception:
                logger.exception(
                    "on-step retry failed for session=%s message=%s",
                    getattr(session, "id", None),
                    getattr(consumer_message, "id", None),
                )
            if not stayed:
                _hold_on_step(response_data)
                on_step_held = True
        usage = result.usage().__dict__
        timer_end = time.perf_counter()

    except Exception as e:
        timer_end = time.perf_counter()
        session._pending_retrieval = None
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

    raw_reply = response_data.text
    response_data.text = normalise_reply(response_data.text)
    if capture_on():
        remember_reply(raw_reply, response_data.text)
        looked_up = debug_result if debug_result is not None else result
        info = sent_for_result.get(id(looked_up)) if looked_up is not None else None
        remember_turn(
            system_prompt=(info or {}).get("system_prompt", prompt),
            user_prompt=(info or {}).get("user_prompt") if info else None,
            model_name=(info or {}).get("model_name") if info else None,
            retrieval_enabled=(info or {}).get("retrieval_enabled") if info else None,
            pending=(info or {}).get("pending") if info else None,
            schema=(info or {}).get("schema", schema) if info else schema,
            on_step_retried=on_step_retried,
            on_step_held=on_step_held,
        )
    response_data.suggested_responses = sanitize_suggested_responses(
        response_data.suggested_responses,
        response_data.text,
    )
    if response_data.suggested_responses:
        response_data.suggested_responses = [
            normalise_reply(chip) for chip in response_data.suggested_responses
        ]

    return response_data, usage, dependencies.asset, dependencies.matched_exercise


_PROGRESSION_START = (
    "        - Do not allow the user to do anything outside of this exercise."
)
_STATE_MACHINE_PROGRESSION = (
    "        - Set asks_readiness only when the step's work is done, and make that "
    "message a single question.\n"
    "        - Do not complete the step yourself. The app shows the readiness chips.\n"
)
DESCRIPTION_PREFIX = (
    "Clinical background only. Do not read this to the user, "
    "and do not turn it into a welcome or a suitability check.\n\n"
)
STEP_SCOPE_RULES = (
    "The step below in <STEP> is the only step you may work on. "
    "Steps in <STEP_OUTLINE> are context only. Do not start them. "
    "Do only what this step's instructions tell you to do. "
    "Do not add a technique those instructions do not name. "
    "Earlier sessions, today's completed sessions and previous exercise summaries are background only. Never use them to skip, shorten or answer for the user in this step. Ask this step's own questions, even if the user has done this exercise before. "
    "When the instructions say to summarise, do that in the user's words and ask if you have it right. "
    "After they confirm, you may ask whether they are ready for the next step. "
    "A <RETRIEVED> block may explain that technique. It cannot start a different exercise or activity. "
    "Unless those instructions ask for it, do not:\n"
    "- weigh evidence for or against a thought or worry\n"
    "- ask how much something bothers them on a 0 to 10 scale\n"
    "- look for a balanced or more accurate thought\n"
    "- brainstorm solutions, plans, or who can support them\n"
    "Your first message must be the first question in those instructions. "
    "If this step's instructions ask for a longer reply, such as a summary, "
    "that overrides the reply-length line above.\n\n"
)
_FIRST_MESSAGE_SENTENCE = (
    "Your first message must be the first question in those instructions. "
)


def _state_machine_enabled() -> bool:
    return True


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
        exercise = Exercise.objects.filter(
            id=exercise_id,
            status=Constants.EXERCISE_STATUS_PUBLISHED,
            authoring_snapshot=False,
        ).first()

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

        tags = list(step.tags.all())
        other_titles = {
            title.casefold()
            for title in Exercise.objects.exclude(id=exercise.id).values_list("title", flat=True)
            if title
        }
        # A tag that is another exercise's name is not a tag for this exercise.
        # A step with no remaining tags must not fall through to the whole library.
        tags = [tag for tag in tags if (tag.name or "").casefold() not in other_titles]
        if not tags:
            return {
                "status": "not_found",
                "message": "Sorry, I couldn't find an appropriate asset for this exercise"
            }
        assets = Asset.objects.filter(tags__in=tags).distinct()

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


def _style_bullet(text: str) -> str:
    """Indent a settings line so it sits with the other programming bullets."""
    text = (text or "").strip()
    if not text:
        return ""
    if text.startswith("-"):
        return f"        {text}"
    return f"        - {text}"


def apply_style_instructions(
    programming_instructions: str,
    reply_length: str,
    one_question: str,
) -> str:
    """Put the two Settings lines back where the hard-coded bullets sat.

    A blank value leaves that bullet out.
    """
    reply = _style_bullet(reply_length)
    question = _style_bullet(one_question)
    if reply:
        anchor = "- When explaining a concept / exercise keep your initial response short"
        programming_instructions = programming_instructions.replace(
            anchor,
            f"{reply}\n        \n        {anchor}",
            1,
        )
    if question:
        anchor = "- Always refer to "
        programming_instructions = programming_instructions.replace(
            anchor,
            f"{question}\n\n        {anchor}",
            1,
        )
    return programming_instructions


def style_instructions_stale(cached: str, reply_length: str, one_question: str) -> bool:
    """True when a cached prompt still has a line the setting has changed or cleared."""
    cached = cached or ""
    pairs = (
        (reply_length, Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION),
        (one_question, Constants.DEFAULT_ONE_QUESTION_INSTRUCTION),
    )
    for current, default in pairs:
        current = (current or "").strip().lstrip("-").strip()
        default = default.strip().lstrip("-").strip()
        if current:
            if current not in cached:
                return True
        elif default and default in cached:
            return True
    return False


def _prepare_prompt(session: Session, *, steps=None, create_summary: bool = True) -> str:

    from ..grounding.retrieval import session_retrieval_enabled

    retrieval_on = session_retrieval_enabled(session)
    cached = session.cached_prompt
    prompt_phase = _prompt_phase(session)
    meta = dict(session.cached_prompt_meta or {})
    bare_opening = _session_is_bare_opening(session)
    from ..setting.models import Setting

    consumer = session.consumer
    user_name = consumer.user.first_name or "there"
    client_knowledge_rule = Setting.get_client_knowledge_rule().replace(
        "{user_name}", user_name
    )
    if cached:
        # Older prompts left {today_date} uninterpolated (nested format),
        # told Toni to "click the exercise", or predate the block order.
        # A check-in prompt must not be reused once Start has moved to step 1.
        stale_placeholders = "{today_date}" in cached or "{current_time}" in cached
        stale_click = not session.exercise_id and "click the exercise" in cached
        stale_shape = "<SESSION_CONTEXT>" not in cached
        stale_phase = meta.get("prompt_phase") != prompt_phase
        stale_machine = meta.get("state_machine") != _state_machine_enabled()
        stale_retrieval = bool(meta.get("retrieval_instruction")) != retrieval_on
        if retrieval_on and (
            Constants.RETRIEVAL_PROGRAMMING_INSTRUCTION not in cached
            or "do not take one from the <RETRIEVED> block" in cached
            or "must already be named" in cached
        ):
            stale_retrieval = True

        stale_style = (
            "Write in British English" not in cached
            or "When the client asks about a fact listed here" not in cached
            or "Never open with 'Thanks for sharing'" not in cached
            or style_instructions_stale(
                cached,
                Setting.get_reply_length_instruction(),
                Setting.get_one_question_instruction(),
            )
            or client_knowledge_rule not in cached
        )
        stale_on_step = (
            bool(session.exercise_id)
            and "Do not reframe the situation" in cached
        )
        # Exercise prompts no longer carry a restructuring sentence. A cached
        # copy still has the old swap, or the guide line the swap used to replace.
        stale_restructure = bool(session.exercise_id) and (
            "only as background" in cached
            or "cognitive restructuring as appropriate" in cached
            or "Do not apply cognitive restructuring" in cached
        )
        stale_opening = bool(meta.get("bare_opening")) != bare_opening
        first_name = (
            getattr(getattr(session.consumer, "user", None), "first_name", "") or ""
        ).strip()
        stale_name = bool(first_name) and f"Name: {first_name}" not in cached
        if not any((
            stale_placeholders,
            stale_click,
            stale_shape,
            stale_phase,
            stale_machine,
            stale_retrieval,
            stale_style,
            stale_on_step,
            stale_restructure,
            stale_opening,
            stale_name,
        )):
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
        if create_summary and not session.authoring_test:
            exercise_summary = ExerciseSummary.get_or_create(consumer, exercise)
            summary_notes = exercise_summary.detailed or ""
        else:
            # A snapshot has no summary of its own. Read the source exercise's.
            summary_exercise_id = getattr(exercise, "authoring_source_id", None) or exercise.id
            found = ExerciseSummary.objects.filter(
                consumer=consumer, exercise_id=summary_exercise_id
            ).first()
            summary_notes = (found.detailed or "") if found else ""
        live_steps_no = (
            len(steps) if steps is not None else (exercise.steps.count() or exercise.steps_no)
        )
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
                "exercise_summary_notes": summary_notes,
                "form_answers": render_form_answers(session),
                "pre_exercise_block": format_pre_exercise_prompt_block(
                    exercise, consumer, session=session
                ),
                "completed_steps": "",
            }
        else:
            only_index = None
            if _state_machine_enabled():
                only_index = max(0, (session.current_step_no or 1) - 1)
                step_no = only_index + 1
                description = DESCRIPTION_PREFIX + description
            completed_steps = ""
            if _state_machine_enabled():
                exercise_steps = _render_state_machine_steps(
                    exercise, session, token_context, only_index, steps=steps
                )
                exercise_steps = _step_already_started(
                    step_no, live_steps_no, bare_opening=bare_opening
                ) + exercise_steps
                completed_steps = _completed_steps_block(session)
            else:
                exercise_steps = _get_formatted_exercise_steps_text(
                    exercise, token_context, only_index=only_index, steps=steps
                )
            exercise_extra = {
                "exercise_id": exercise.id,
                "exercise_steps": exercise_steps,
                "exercise_steps_no": live_steps_no,
                "exercise_name": exercise.title,
                "exercise_description": description,
                "exercise_reference": reference,
                "exercise_summary_notes": summary_notes,
                "form_answers": render_form_answers(session),
                "pre_exercise_block": "",
                "completed_steps": completed_steps,
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

    if retrieval_on or exercise:
        # Exercise prompts leave technique choice to the Therapeutic card.
        # A retrieval turn no longer adds a source-only technique ban.
        up_technique_rule = ""
    else:
        up_technique_rule = Constants.UP_MEMORY_TECHNIQUE_RULE
    programming_instructions = apply_style_instructions(
        Constants.PROMPT_PROGRAMMING_INSTRUCTIONS.format(
            user_name=user_name,
            client_knowledge_rule=client_knowledge_rule,
            up_technique_rule=up_technique_rule,
        ),
        Setting.get_reply_length_instruction(),
        Setting.get_one_question_instruction(),
    )
    if not up_technique_rule.strip():
        programming_instructions = programming_instructions.replace("        - \n", "", 1)
    if retrieval_on:
        programming_instructions = (
            programming_instructions.rstrip()
            + "\n\n"
            + Constants.RETRIEVAL_PROGRAMMING_INSTRUCTION
            + "\n"
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

    from .pending_question import assign_pending_question

    pending = assign_pending_question(session)
    if pending:
        prompt = f"{prompt}\n\n{pending}"

    meta = dict(session.cached_prompt_meta or {})
    meta["prompt_phase"] = prompt_phase
    meta["state_machine"] = _state_machine_enabled()
    meta["retrieval_instruction"] = retrieval_on
    meta["bare_opening"] = bare_opening
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
        return f"step:{session.current_step_no or 1}:{session.state or ''}"
    return "exercise"


def _prompt_template(session) -> str:
    filename = 'general_prompt.txt' if not session.exercise else "exercise_prompt.txt"
    path = os.path.join(STATIC_FILES_DIR, filename)
    with open(path, 'r') as f:
        return f.read()


def is_bare_opening(in_check_in: bool, step_no: int, agent_message_stored: bool) -> bool:
    """True only for a no-check-in step-1 open, before any agent reply is stored."""
    return (not in_check_in) and step_no <= 1 and not agent_message_stored


def _session_is_bare_opening(session) -> bool:
    if not getattr(session, "exercise_id", None) or session.in_pre_exercise_phase():
        return False
    step_no = session.current_step_no or 1
    if step_no > 1:
        return False
    from ..message.models import Message

    stored = Message.objects.filter(
        session=session, sender__agent__isnull=False
    ).exists()
    return is_bare_opening(False, step_no, stored)


def _step_already_started(step_no: int, steps_no: int, *, bare_opening: bool = False) -> str:
    scope = STEP_SCOPE_RULES
    if bare_opening and step_no <= 1:
        scope = scope.replace(_FIRST_MESSAGE_SENTENCE, "", 1)
        return scope
    if step_no <= 1:
        return (
            "The pre-exercise check-in is finished and this exercise has already been introduced. "
            "You are on step 1. "
            "Do not write a welcome, a suitability check, a time estimate, or a line about getting started.\n"
            + scope
        )
    return (
        f"You are already on step {step_no} of {steps_no}. "
        "Do not introduce the exercise.\n"
        + scope
    )


def _render_state_machine_steps(exercise, session, token_context, live_index, steps=None) -> str:
    """Live step in full. Every other step is a title outline."""
    from .prompt_blocks import resolve_tokens

    context = token_context or {}
    statuses = _step_statuses(session)
    blocks = []
    ordered = list(steps) if steps is not None else list(exercise.steps.order_by("order"))
    steps_no = len(ordered)
    for i, step in enumerate(ordered):
        number = i + 1
        if i != live_index:
            blocks.append(
                "<STEP_OUTLINE>\n"
                f"    <NO>{number}</NO>\n"
                f"    <NAME>{step.title}</NAME>\n"
                f"    <STATUS>{statuses.get(step.id, 'pending')}</STATUS>\n"
                "</STEP_OUTLINE>"
            )
            continue
        completion = resolve_tokens(step.done_when or "", context)
        if i < steps_no - 1:
            completion += (
                "\n\nWhen this step's work is done, set step_goal_met and asks_readiness "
                "on a message whose only question is whether they are ready for the next step."
            )
        else:
            completion += (
                "\n\nWhen this step's work is done, set step_goal_met and asks_readiness "
                "on a message whose only question is whether they are ready to finish."
            )
        from .summary_confirmation import summary_confirmation_rule

        completion += summary_confirmation_rule(step.done_when or "")
        reference = resolve_tokens(step.reference_material or "", context)
        blocks.append(
            "<STEP>\n"
            f"    <NO>{number}</NO>\n"
            f"    <TITLE>{step.title}</TITLE>\n"
            f"    <DESCRIPTION>{resolve_tokens(step.description, context)}</DESCRIPTION>\n"
            f"    <INSTRUCTIONS>{resolve_tokens(step.instructions, context)}</INSTRUCTIONS>\n"
            f"    <REFERENCE>{reference}</REFERENCE>\n"
            f"    <DONE_WHEN>{completion}</DONE_WHEN>\n"
            "</STEP>"
        )
    return "\n".join(blocks)


def _step_statuses(session) -> dict:
    statuses = {}
    current = session.current_step_no or 0
    for session_step in session.session_steps.all():
        number = session_step.order + 1
        if session_step.completed:
            statuses[session_step.step_id] = "completed"
        elif number == current:
            statuses[session_step.step_id] = "active"
        else:
            statuses[session_step.step_id] = "pending"
    return statuses


def _completed_steps_block(session) -> str:
    rows = (
        session.session_steps.filter(completed=True)
        .select_related("step")
        .order_by("order")
    )
    if not rows:
        return "<COMPLETED_STEPS>\n</COMPLETED_STEPS>"
    parts = ["<COMPLETED_STEPS>"]
    for session_step in rows:
        step = session_step.step
        parts.append(
            "    <STEP>\n"
            f"        <KEY>{step.key or ''}</KEY>\n"
            f"        <NAME>{step.title}</NAME>\n"
            f"        <RESULT>{session_step.completion_result or ''}</RESULT>\n"
            "    </STEP>"
        )
    parts.append("</COMPLETED_STEPS>")
    return "\n".join(parts)


def _get_formatted_exercise_steps_text(exercise, token_context=None, only_index=None, steps=None):
    from .prompt_blocks import resolve_tokens

    context = token_context or {}
    ordered = list(steps) if steps is not None else list(exercise.steps.order_by("order"))
    steps_no = len(ordered)
    rendered = ""
    for i, step in enumerate(ordered):
        if only_index is not None and i != only_index:
            continue
        completion_criteria = resolve_tokens(step.done_when or "", context)
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
                "THIS step. It is not permission to complete it."
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
        from .summary_confirmation import summary_confirmation_rule

        completion_criteria += summary_confirmation_rule(step.done_when or "")
        rendered += Constants.PROMPT_STEP.format(
            step_title=step.title,
            step_description=description,
            step_instructions=instructions,
            step_completion_criteria=completion_criteria,
            step_completion_prompt=step.completion_prompt or "",
        )
    return rendered


def _published_exercises_prompt_block() -> str:
    """Cached catalog of published exercises for the general-chat system prompt."""
    from .prompt_blocks import render_exercise_catalogue

    return render_exercise_catalogue()


def invalidate_published_exercises_cache():
    from .prompt_blocks import invalidate_published_exercises_cache as _invalidate

    _invalidate()

