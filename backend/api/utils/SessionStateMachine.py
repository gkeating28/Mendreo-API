"""Exercise session transitions. Active only when AI_STATE_MACHINE_ENABLED is on.

Code owns the step. The model reports step_goal_met and asks_readiness.
Chip taps do not call the chat model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.db.models import F
from django.utils import timezone

from . import Constants

logger = logging.getLogger(__name__)

DEFAULT_SUCCESS_TITLE = "Well Done!"


def enabled() -> bool:
    return True


@dataclass
class ChipOutcome:
    message: object
    session_state: dict


def phase_of(session) -> str:
    if not session.exercise_id:
        return Constants.SESSION_STATE_GENERAL
    if session.completed or session.state == Constants.SESSION_STATE_COMPLETED:
        return Constants.SESSION_STATE_COMPLETED
    if session.abandoned or session.state == Constants.SESSION_STATE_ABANDONED:
        return Constants.SESSION_STATE_ABANDONED
    # Check-in is the step number, not a stale state value. A session can be
    # stored as check_in after current_step_no has already moved to 1.
    if session.in_pre_exercise_phase():
        return Constants.SESSION_STATE_CHECK_IN
    if session.state == Constants.SESSION_STATE_AWAITING_READY:
        return Constants.SESSION_STATE_AWAITING_READY
    return Constants.SESSION_STATE_STEP_ACTIVE


def build_session_state(session, completion_card=None) -> dict:
    phase = phase_of(session)
    if phase == Constants.SESSION_STATE_GENERAL:
        payload = {
            "session_id": session.id,
            "exercise_id": None,
            "phase": phase,
            "current_step_no": None,
            "steps": None,
            "pending_action": "none",
            "risk_level": session.live_risk_level or Constants.LIVE_RISK_LEVEL_NONE,
        }
        if completion_card:
            payload["completion_card"] = completion_card
        return payload

    steps = []
    current = session.current_step_no or 0
    for session_step in session.session_steps.select_related("step").order_by("order"):
        number = session_step.order + 1
        if session_step.completed:
            status = "completed"
        elif phase != Constants.SESSION_STATE_CHECK_IN and number == current:
            status = "active"
        else:
            status = "pending"
        steps.append(
            {
                "no": number,
                "key": session_step.step.key,
                "name": session_step.step.title,
                "status": status,
                "completion_result": session_step.completion_result,
            }
        )

    total = len(steps)
    pending = "none"
    if phase == Constants.SESSION_STATE_CHECK_IN:
        pending = "start"
    elif phase == Constants.SESSION_STATE_AWAITING_READY:
        pending = "finish" if total and current >= total else "ready"

    payload = {
        "session_id": session.id,
        "exercise_id": session.exercise_id,
        "phase": phase,
        "current_step_no": current,
        "steps": steps,
        "pending_action": pending,
        "risk_level": session.live_risk_level or Constants.LIVE_RISK_LEVEL_NONE,
    }
    if completion_card:
        payload["completion_card"] = completion_card
    return payload


def initial_state(exercise, run_pre_exercise: bool) -> str:
    if not exercise:
        return Constants.SESSION_STATE_GENERAL
    if run_pre_exercise:
        return Constants.SESSION_STATE_CHECK_IN
    return Constants.SESSION_STATE_STEP_ACTIVE


_MODEL_READY_CHIPS = re.compile(
    r"^(?:"
    r"(?:yes[, ]+)?(?:i['’]m |i am )?ready(?: (?:to|for) (?:continue|proceed|move on|start|the next step))?"
    r"|not yet"
    r"|finish(?: the)? exercise"
    r"|(?:yes[, ]+)?(?:let['’]s |lets )?(?:move on|continue|start)(?: to the next step)?"
    r"|next step"
    r")[.!?…]*$",
    re.IGNORECASE,
)


def prepare_model_readiness(session, response, question_kind, chips, text):
    """Drop model-authored readiness chips. Code asks that question."""
    if session.state == Constants.SESSION_STATE_AWAITING_READY:
        return question_kind, chips

    asks = bool(getattr(response, "asks_readiness", False))
    live = _live_step(session)
    goal_met = bool(getattr(response, "step_goal_met", False)) or bool(
        live and live.goal_met_at
    )
    official = (
        asks
        and goal_met
        and not session.in_pre_exercise_phase()
        and live is not None
    )
    if official:
        return Constants.QUESTION_KIND_READINESS, []

    if question_kind == Constants.QUESTION_KIND_READINESS:
        question_kind = (
            Constants.QUESTION_KIND_OPEN
            if (text or "").strip().endswith("?")
            else Constants.QUESTION_KIND_NONE
        )
    kept = [
        chip
        for chip in (chips or [])
        if not is_model_ready_chip(chip)
    ]
    return question_kind, kept


def is_model_ready_chip(chip) -> bool:
    """True when the whole chip is a readiness or advance phrase."""
    return bool(_MODEL_READY_CHIPS.match(str(chip or "").strip()))


def on_model_turn(session, agent_message, response) -> None:
    """Apply asks_readiness / step_goal_met after the agent message is saved."""
    if session.in_pre_exercise_phase():
        return
    if not getattr(session, "exercise_id", None):
        return

    model_goal = bool(getattr(response, "step_goal_met", False))
    model_asks = bool(getattr(response, "asks_readiness", False))
    goal_met = model_goal
    asks = model_asks
    inferred_asks = model_asks
    accepted_goal = goal_met
    session._step_check_result = None
    session._step_goal_hint_written = None
    try:
        if session.state == Constants.SESSION_STATE_CHECK_IN:
            session.state = Constants.SESSION_STATE_STEP_ACTIVE
            session.save(update_fields=["state", "updated_at"])

        session_step = _live_step(session)
        text = (getattr(agent_message, "text", None) or "").strip()
        if model_goal and not asks and _ends_with_readiness_question(text):
            asks = True
            inferred_asks = True
        # A question is still waiting for the user's answer, so the goal is not met yet.
        if text.endswith("?") and not asks:
            goal_met = False

        accepted_goal = goal_met
        advisory = (
            model_goal
            and _ends_with_readiness_question(text)
            and not _is_last_step(session)
        )
        if session_step and goal_met and session_step.goal_met_at is None:
            if not _accept_goal(session, session_step, agent_message, advisory=advisory):
                asks = False
                accepted_goal = False

        if not asks or session_step is None or session_step.goal_met_at is None:
            return

        _enter_awaiting_ready(session, agent_message, session_step)
    finally:
        _record_step_decision(
            session,
            agent_message,
            model_goal=model_goal,
            model_asks=model_asks,
            inferred_asks=inferred_asks,
            accepted_goal=accepted_goal,
            accepted_asks=asks,
        )


def consume_chip(user_message, from_suggested_response: bool) -> ChipOutcome | None:
    """Handle ready, finish, and offer chips. None means the chat model should run."""
    if not from_suggested_response:
        return None

    session = user_message.session
    previous = _last_agent_message(session, before=user_message)
    if previous is None:
        return None

    kind = previous.suggested_responses_kind
    text = (user_message.text or "").strip()

    if kind == Constants.SUGGESTED_RESPONSES_KIND_OFFER:
        from .ExerciseOffer import maybe_handle_offer_response

        reply = maybe_handle_offer_response(user_message, True)
        if reply is None:
            return None
        return ChipOutcome(reply, build_session_state(session))

    if kind not in (
        Constants.SUGGESTED_RESPONSES_KIND_READY,
        Constants.SUGGESTED_RESPONSES_KIND_FINISH,
    ):
        return None

    if text == Constants.CHIP_NOT_YET:
        _count_user_message(session, user_message)
        _retreat(session)
        return ChipOutcome(user_message, build_session_state(session))

    if kind == Constants.SUGGESTED_RESPONSES_KIND_READY and text == Constants.CHIP_READY_YES:
        return _confirm(session, user_message)

    if kind == Constants.SUGGESTED_RESPONSES_KIND_FINISH and text == Constants.CHIP_FINISH:
        return _confirm(session, user_message, finishing=True)

    return None


_READY_BLOCK = re.compile(
    r"\b(?:not|no|wait|yet|later)\b|hold on|n't",
    re.IGNORECASE,
)


def _ready_text(text: str) -> str:
    """Lower case, collapsed spaces, trailing . ! and quotes removed."""
    normalised = " ".join(
        (text or "")
        .strip()
        .lower()
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .split()
    )
    return normalised.strip("\"'\u201c\u201d").rstrip(".!").strip("\"'\u201c\u201d")


def _phrase_set(raw) -> set[str]:
    return {normalised for item in raw or [] if (normalised := _ready_text(str(item)))}


def ready_phrase_list_error(phrases) -> str | None:
    """Why a saved phrase list is rejected. None when it can be stored."""
    if not isinstance(phrases, list) or len(phrases) > 30:
        return "Add at most 30 phrases."
    seen: set[str] = set()
    for phrase in phrases:
        if not isinstance(phrase, str):
            return "Each phrase must be 1 to 60 characters."
        text = phrase.strip()
        if not text or len(text) > 60:
            return "Each phrase must be 1 to 60 characters."
        normalised = _ready_text(text)
        if not normalised:
            return "Each phrase must be 1 to 60 characters."
        if normalised in seen:
            return "Phrases must be unique."
        if _READY_BLOCK.search(normalised):
            return (
                "A phrase cannot contain not, no, wait, yet, later, hold on, or n't."
            )
        seen.add(normalised)
    return None


def _ready_phrase_set() -> set[str]:
    from ..setting.models import Setting

    return _phrase_set(Setting.get_ready_phrases())


def _finish_phrase_set() -> set[str]:
    from ..setting.models import Setting

    return _phrase_set(Setting.get_finish_phrases())


def _exact_yes_required() -> bool:
    from ..setting.models import Setting

    return Setting.get_require_exact_yes()


def is_ready_affirmation(text: str) -> bool:
    """A ready-phrase that counts on every step, including the last.

    Next-step wording is excluded here. It matches only through
    is_ready_restatement, and only before the last step.
    """
    if "?" in (text or ""):
        return False
    normalised = _ready_text(text)
    if not normalised or _READY_BLOCK.search(normalised):
        return False
    if normalised in Constants.NEXT_STEP_ONLY_PHRASES:
        return False
    return normalised in _ready_phrase_set()


def is_ready_restatement(text, *, last_step, summary_confirmed) -> bool:
    """Next-step wording before the last step, or finish wording after the summary.

    A ready-phrase that is not next-step wording is an affirmation instead, so
    "yes" still matches on the last step.
    """
    if "?" in (text or ""):
        return False
    normalised = _ready_text(text)
    if not normalised or _READY_BLOCK.search(normalised):
        return False
    if (
        not last_step
        and normalised in _ready_phrase_set()
        and normalised in Constants.NEXT_STEP_ONLY_PHRASES
    ):
        return True
    return bool(
        last_step and summary_confirmed and normalised in _finish_phrase_set()
    )


def _summary_confirmed(session) -> bool:
    session_step = _live_step(session)
    if session_step is None or getattr(session_step, "step", None) is None:
        return False
    from .summary_confirmation import summary_confirmation_required, summary_was_confirmed

    done_when = getattr(session_step.step, "done_when", None) or ""
    if not summary_confirmation_required(done_when):
        return True
    return summary_was_confirmed(session, session_step.step)


def _confirm_typed_ready(session, user_message, *, last_step, summary_confirmed, extracted=None):
    """Finish wording uses the Finish exercise chip's _confirm call."""
    if (
        last_step
        and summary_confirmed
        and _ready_text(user_message.text or "") in _finish_phrase_set()
    ):
        return _confirm(session, user_message, finishing=True)
    if extracted is None:
        return _confirm(session, user_message)
    return _confirm(session, user_message, extracted=extracted)


def confirm_summary_if_done(user_message) -> ChipOutcome | None:
    """An affirmation that meets done_when completes a step that is not the last.

    The last step returns here so the chat model can ask whether they are ready to finish.
    """
    session = user_message.session
    if not session.exercise_id or session.in_pre_exercise_phase():
        return None
    if _is_last_step(session):
        return None
    if session.state != Constants.SESSION_STATE_STEP_ACTIVE:
        return None
    from .summary_confirmation import matches_summary_affirmation

    if not matches_summary_affirmation(user_message.text or ""):
        return None
    session_step = _live_step(session)
    if session_step is None or session_step.completed:
        return None
    if not (getattr(session_step.step, "done_when", None) or "").strip():
        return None

    from .summary_confirmation import is_summary_confirmation, summary_confirmation_required

    done_when = session_step.step.done_when or ""
    if summary_confirmation_required(done_when):
        previous = _last_agent_message(session, before=user_message)
        if previous is None or not is_summary_confirmation(previous.text or ""):
            return None

    from .extraction import check_done_when

    try:
        result = check_done_when(session, session_step.step)
    except Exception:
        logger.exception(
            "summary confirmation check failed for session=%s",
            getattr(session, "id", None),
        )
        return None
    if not result or not result.get("met"):
        return None
    return _confirm(session, user_message)


def _judge_applies(*, last_step, summary_confirmed) -> bool:
    """The model reads a reply only when an exact yes is not required.

    On the last step that wait is the same one finish phrases use: the summary
    has to be confirmed first.
    """
    if _exact_yes_required():
        return False
    if last_step and not summary_confirmed:
        return False
    return True


def _earlier_ready_lines(session, user_message) -> str:
    from ..message.models import Message

    messages = list(
        Message.objects.filter(session=session, created_at__lt=user_message.created_at)
        .select_related("sender")
        .order_by("-created_at")[:2]
    )
    lines = []
    for message in reversed(messages):
        who = "User" if getattr(message.sender, "consumer_id", None) else "Assistant"
        text = (message.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _ready_verdict(session, user_message) -> str:
    """yes, no, or other. A failed check is other, and the chat model still runs."""
    from ..message.turn_prompt import note_turn_decision
    from .extraction import judge_ready_reply

    previous = _last_agent_message(session, before=user_message)
    question = (previous.text or "") if previous is not None else ""
    try:
        answer = judge_ready_reply(
            question=question,
            reply=user_message.text or "",
            earlier=_earlier_ready_lines(session, user_message),
        )
    except Exception:
        logger.exception(
            "ready reply judgement failed for session=%s",
            getattr(session, "id", None),
        )
        answer = "other"
    if answer not in {"yes", "no", "other"}:
        answer = "other"
    if answer == "yes":
        what = "The reply was taken as ready to move on."
        why = "The reply clearly agrees to move on now."
    elif answer == "no":
        what = "The reply was taken as not ready."
        why = "The reply declines, or asks to wait."
    else:
        what = "The reply stayed in the chat."
        why = "The reply is not a clear agreement or refusal."
    note_turn_decision(
        session,
        {
            "type": "ready_reply",
            "fired": answer == "yes",
            "what": what,
            "why": why,
            "inputs": {"verdict": answer},
        },
    )
    return answer


def _retreat_outcome(session, user_message) -> ChipOutcome:
    _count_user_message(session, user_message)
    _retreat(session)
    return ChipOutcome(user_message, build_session_state(session))


def _confirm_listed_ready(session, user_message, session_step, *, last_step, summary_confirmed, text):
    if _ready_text(text) in _finish_phrase_set() and last_step and summary_confirmed:
        return _confirm(session, user_message, finishing=True)

    from .extraction import extract_step_result

    try:
        extracted = extract_step_result(session, session_step.step) or {}
    except Exception:
        logger.exception(
            "readiness confirmation extract failed for session=%s",
            getattr(session, "id", None),
        )
        extracted = {}
    return _confirm(session, user_message, extracted=extracted)


def confirm_readiness_reply(user_message) -> ChipOutcome | None:
    """A yes after Toni asked to move on completes the step.

    A phrase from the lists confirms without a model call. Any other reply is
    read by the model unless an exact yes is required. A clear no returns to
    the step. Anything else stays in the chat.
    """
    session = user_message.session
    if not session.exercise_id or session.in_pre_exercise_phase():
        return None
    if session.state != Constants.SESSION_STATE_STEP_ACTIVE:
        return None
    last_step = _is_last_step(session)
    summary_confirmed = _summary_confirmed(session) if last_step else False
    text = user_message.text or ""
    listed = is_ready_affirmation(text) or is_ready_restatement(
        text, last_step=last_step, summary_confirmed=summary_confirmed
    )
    if not listed and not _judge_applies(
        last_step=last_step, summary_confirmed=summary_confirmed
    ):
        return None
    session_step = _live_step(session)
    if session_step is None or session_step.completed:
        return None
    previous = _last_agent_message(session, before=user_message)
    if previous is None:
        return None

    from .StepProgress import is_advance_gate_text

    if not is_advance_gate_text(previous.text):
        return None

    if not listed:
        verdict = _ready_verdict(session, user_message)
        if verdict == "no":
            return _retreat_outcome(session, user_message)
        if verdict != "yes":
            return None
    return _confirm_listed_ready(
        session,
        user_message,
        session_step,
        last_step=last_step,
        summary_confirmed=summary_confirmed,
        text=text,
    )


def handle_typed_while_awaiting(user_message) -> ChipOutcome | None:
    """A typed reply while waiting for readiness.

    A listed phrase confirms the step and does not call a model. When an exact
    yes is not required, the model reads anything else. yes confirms, no goes
    back to the step, and other leaves the session waiting so the chat model
    can answer. The session stays awaiting_ready on other, so the next typed
    reply is judged again.
    """
    session = user_message.session
    if session.state != Constants.SESSION_STATE_AWAITING_READY:
        return None
    last_step = _is_last_step(session)
    summary_confirmed = _summary_confirmed(session) if last_step else False
    text = user_message.text or ""
    if is_ready_affirmation(text) or is_ready_restatement(
        text, last_step=last_step, summary_confirmed=summary_confirmed
    ):
        return _confirm_typed_ready(
            session,
            user_message,
            last_step=last_step,
            summary_confirmed=summary_confirmed,
        )
    if _judge_applies(last_step=last_step, summary_confirmed=summary_confirmed):
        verdict = _ready_verdict(session, user_message)
        if verdict == "yes":
            return _confirm_typed_ready(
                session,
                user_message,
                last_step=last_step,
                summary_confirmed=summary_confirmed,
            )
        if verdict == "no":
            return _retreat_outcome(session, user_message)
        return None
    return _retreat_outcome(session, user_message)


def ready_gate_catalogue_text() -> str:
    """Built-in rules text. Settings are live; a database error falls back to the seeds."""
    try:
        from ..setting.models import Setting

        exact = Setting.get_require_exact_yes()
        ready = list(Setting.get_ready_phrases())
        finish = list(Setting.get_finish_phrases())
    except Exception:
        exact = False
        ready = list(Constants.DEFAULT_READY_PHRASES)
        finish = list(Constants.DEFAULT_FINISH_PHRASES)
    exact_line = "On" if exact else "Off"
    summary = ", ".join(sorted(Constants.SUMMARY_AFFIRMATIONS))
    next_only = ", ".join(sorted(Constants.NEXT_STEP_ONLY_PHRASES))
    return (
        "Ready gate. A typed reply while the session is waiting to move on.\n"
        f"Require an exact yes: {exact_line}. Editable in Settings (require_exact_yes).\n"
        "Off: a reply that is not in the lists is read by the AI. "
        "yes moves the step on, no goes back to the step, other stays in the chat.\n"
        "On: only the phrases below and the chips move a step on.\n"
        "If both lists are empty and this is on, only the chips move the step on.\n"
        "Next-step phrases match only before the last step. "
        "On the last step, ready phrases still match yes and I'm ready. "
        "Finish phrases match only after the summary was confirmed.\n"
        f"Ready phrases, editable in Settings (ready_phrases): {', '.join(ready)}\n"
        f"Finish phrases, editable in Settings (finish_phrases): {', '.join(finish)}\n"
        "Next-step-only phrases, still in code (NEXT_STEP_ONLY_PHRASES): "
        f"{next_only}\n"
        "Summary agreement, still in code (SUMMARY_AFFIRMATIONS): "
        f"{summary}\n"
        "is_summary_affirmation also accepts a short start such as correct, right, "
        "exactly, that's right, sounds good, looks good, or perfect. Still in code.\n"
        "Chips, still in code: "
        f"{Constants.CHIP_READY_YES}; {Constants.CHIP_NOT_YET}; {Constants.CHIP_FINISH}."
    )


HIDDEN_OPENER_STEP_ONE = (
    "The exercise has already been introduced during the check-in. "
    "Ask the first question of step 1 now. "
    "Do not welcome the user, explain the exercise, or ask if it is right for them."
)
HIDDEN_OPENER_LATER = (
    "Continue straight into step {step_no}. "
    "Ask only the first question that step's instructions require. "
    "Do not introduce the exercise."
)
HIDDEN_OPENER_GREET_REPEAT = (
    "Hi, I'd like to practise this exercise again. "
    "Please start with the pre-exercise check-in before we begin Step 1."
)
# No instruction. The step 1 text in the system prompt is what the model follows.
HIDDEN_OPENER_START = "start"


def hidden_opener_catalogue_text() -> str:
    """Every hidden opener the runner can send. Built from the constants above."""
    return "\n\n".join(
        (
            "No-check-in step-1 open:\n" + HIDDEN_OPENER_START,
            "After a check-in, step 1:\n" + HIDDEN_OPENER_STEP_ONE,
            "Later step:\n" + HIDDEN_OPENER_LATER,
            "Check-in:\n" + HIDDEN_OPENER_GREET_REPEAT,
        )
    )


def greeting_text(session, synthetic_text=None) -> str:
    """Hidden user turn for a session greeting. Not shown in the chat."""
    if synthetic_text:
        return synthetic_text
    if session.in_pre_exercise_phase():
        return HIDDEN_OPENER_GREET_REPEAT
    if (session.current_step_no or 1) <= 1:
        return HIDDEN_OPENER_START
    return opening_turn(session.current_step_no)


def opening_turn(step_no: int) -> str:
    """Hidden user turn that opens a step. It is not shown in the chat.

    "Begin step N" makes the model write a welcome. This tells it the
    exercise is already underway and to ask the step's first question.
    """
    if step_no <= 1:
        return HIDDEN_OPENER_STEP_ONE
    return HIDDEN_OPENER_LATER.format(step_no=step_no)


def start_check_in(session, summary=None):
    """Move check-in to step 1 and open the step with a synthetic turn."""
    from ..exercise.pre_exercise import complete_pre_exercise_checkin

    if not session.in_pre_exercise_phase():
        raise ValueError("Session is not in the pre-exercise check-in phase")

    return complete_pre_exercise_checkin(
        session,
        summary=summary,
        synthetic_text=opening_turn(1),
    )


def confirm_ready(session, confirm: bool):
    """Explicit POST /ready. Persists the chip text, then transitions."""
    from ..message.models import Message
    from ..participant.models import Participant

    if session.state != Constants.SESSION_STATE_AWAITING_READY:
        raise ValueError("This session is not waiting for a readiness reply.")

    text = Constants.CHIP_READY_YES if confirm else Constants.CHIP_NOT_YET
    sender = Participant.objects.filter(session=session, consumer=session.consumer).first()
    user_message = Message.objects.create(session=session, sender=sender, text=text)
    if not confirm:
        _count_user_message(session, user_message)
        _retreat(session)
        return ChipOutcome(user_message, build_session_state(session))
    return _confirm(session, user_message)


def finish_exercise(session):
    """Explicit POST /finish."""
    from ..message.models import Message
    from ..participant.models import Participant

    if session.state != Constants.SESSION_STATE_AWAITING_READY:
        raise ValueError("This session is not ready to finish.")

    sender = Participant.objects.filter(session=session, consumer=session.consumer).first()
    user_message = Message.objects.create(
        session=session,
        sender=sender,
        text=Constants.CHIP_FINISH,
    )
    return _confirm(session, user_message, finishing=True)


def skip_step(session, user_message):
    """QA skip. Completes the live step without the chat model."""
    from ..message.models import Message
    from ..participant.models import Participant

    agent = Participant.objects.filter(session=session, agent=session.consumer.agent).first()
    step_no = session.current_step_no or 1
    session_step = _live_step(session)
    label = session_step.step.completion_label if session_step else None
    agent_message = Message.objects.create(
        session=session,
        sender=agent,
        text="Step skipped.",
        reasoning="Skip step triggered",
        suggested_responses=[],
        completion_label=label,
        question_kind=Constants.QUESTION_KIND_NONE,
    )
    outcome = _confirm(
        session,
        user_message,
        finishing=_is_last_step(session),
        extracted={"value": "Step Skipped", "confidence": 1.0},
        readiness_message=agent_message,
        count_user=False,
    )
    if outcome.message is not None and outcome.message.id != user_message.id:
        return outcome.message
    return agent_message


def _confirm(
    session,
    user_message,
    finishing=False,
    extracted=None,
    readiness_message=None,
    count_user=True,
):
    from ..exercise.models import Exercise
    from .AIWorkerClient import request_session_greeting
    from .extraction import extract_step_result

    session_step = _live_step(session)
    step = session_step.step if session_step else None
    step_no = session.current_step_no or 1
    if extracted is None and step is not None:
        extracted = extract_step_result(session, step)

    value = (extracted or {}).get("value")
    confidence = (extracted or {}).get("confidence")
    label = step.completion_label if step else None
    title = (step.success_title if step else None) or DEFAULT_SUCCESS_TITLE

    if session_step:
        session_step.completed = True
        session_step.completion_result = value
        session_step.completion_label = label
        session_step.result_confidence = confidence
        session_step.save(
            update_fields=[
                "completed",
                "completion_result",
                "completion_label",
                "result_confidence",
                "updated_at",
            ]
        )

    readiness = readiness_message or _last_agent_message(session, before=user_message)
    if readiness is not None:
        readiness.completion_label = label
        readiness.save(update_fields=["completion_label", "updated_at"])

    if count_user:
        _count_user_message(session, user_message)
    total = session.session_steps.count() or session.total_steps_no or step_no
    last = finishing or step_no >= total
    session.cached_prompt = None

    greeting = None
    if last:
        session.state = Constants.SESSION_STATE_COMPLETED
        session.current_step_no = total + 1
        session.mark_completed()
        session.save(
            update_fields=[
                "state",
                "current_step_no",
                "cached_prompt",
                "completed",
                "completed_at",
                "messages_no",
                "consumer_messages_no",
                "last_message",
                "updated_at",
            ]
        )
        if not session.authoring_test:
            Exercise.all_objects.filter(id=session.exercise_id).update(
                completions_no=F("completions_no") + 1
            )
    else:
        session.state = Constants.SESSION_STATE_STEP_ACTIVE
        session.current_step_no = step_no + 1
        meta = dict(session.cached_prompt_meta or {})
        meta.pop("goal_hint", None)
        meta.pop("depth_hint_step_id", None)
        meta.pop("done_when_rejections", None)
        session.cached_prompt_meta = meta
        session.save(
            update_fields=[
                "state",
                "current_step_no",
                "cached_prompt",
                "cached_prompt_meta",
                "messages_no",
                "consumer_messages_no",
                "last_message",
                "updated_at",
            ]
        )
        if getattr(session, "authoring_test", False):
            from .AIWorkerClient import _run_session_greeting
            from .authoring_run import model_failure_reason

            greeting = _run_session_greeting(
                session,
                synthetic_text=opening_turn(step_no + 1),
            )
            reason = model_failure_reason(greeting)
            if reason:
                raise RuntimeError(reason)
        else:
            greeting = request_session_greeting(
                session,
                synthetic_text=opening_turn(step_no + 1),
            )

    card = {"title": title, "label": label or ""}
    display = greeting or user_message
    return ChipOutcome(display, build_session_state(session, completion_card=card))


def _accept_goal(session, session_step, agent_message, *, advisory: bool = False) -> bool:
    """Stamp goal_met_at only after done_when, and depth when it is due, both pass."""
    if not _done_when_passed(session, session_step, agent_message, advisory=advisory):
        return False
    if _depth_check_due(session, session_step) and not _depth_check_passed(session, session_step):
        _downgrade_readiness(agent_message)
        return False
    session_step.goal_met_at = timezone.now()
    session_step.save(update_fields=["goal_met_at", "updated_at"])
    return True


_INFERRED_READINESS = re.compile(
    r"(?:"
    r"ready to conclude"
    r"|ready to finish"
    r"|ready to wrap up"
    r"|ready to put"
    r"|ready to summari[sz]e"
    r")",
    re.IGNORECASE,
)


def _closing_sentence(text: str) -> str:
    raw = (text or "").strip()
    parts = re.split(r"(?<=[.!])\s+", raw)
    return parts[-1] if parts else ""


def _ends_with_readiness_question(text: str) -> bool:
    """True when the reply's last sentence is a readiness question."""
    closing = _closing_sentence(text)
    if not closing.endswith("?"):
        return False
    from .StepProgress import is_advance_gate_text

    if is_advance_gate_text(closing):
        return True
    return bool(_INFERRED_READINESS.search(closing))


def _done_when_rejection_count(session) -> int:
    record = (session.cached_prompt_meta or {}).get("done_when_rejections")
    if not isinstance(record, dict):
        return 0
    try:
        return int(record.get(str(session.current_step_no or 1)) or 0)
    except (TypeError, ValueError):
        return 0


def _note_done_when_rejection(session) -> None:
    meta = dict(session.cached_prompt_meta or {})
    record = dict(meta.get("done_when_rejections") or {})
    step_no = str(session.current_step_no or 1)
    try:
        count = int(record.get(step_no) or 0)
    except (TypeError, ValueError):
        count = 0
    record[step_no] = count + 1
    meta["done_when_rejections"] = record
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])


def _done_when_passed(session, session_step, agent_message, *, advisory: bool = False) -> bool:
    from .extraction import check_done_when

    if not advisory and _done_when_rejection_count(session) >= 2:
        result = {"met": True, "missing": "", "forced": True}
    else:
        try:
            result = check_done_when(session, session_step.step)
        except Exception:
            logger.exception(
                "done_when check failed for session=%s step=%s",
                getattr(session, "id", None),
                getattr(session_step, "id", None),
            )
            result = {"met": True}
    _remember_check_result(session, result)
    done_when = getattr(session_step.step, "done_when", None) or ""
    from .summary_confirmation import summary_confirmation_required, summary_was_confirmed

    if (result is None or result.get("met")) and summary_confirmation_required(done_when):
        if not summary_was_confirmed(session, session_step.step):
            if not result.get("forced"):
                _downgrade_readiness(agent_message)
                _store_summary_hint(session)
                _note_done_when_rejection(session)
                return False
    if result is None or result.get("met") or advisory:
        return True
    _downgrade_readiness(agent_message)
    _store_goal_hint(session, result.get("missing") or "")
    _note_done_when_rejection(session)
    return False


def _store_summary_hint(session) -> None:
    from .turn_hint import SUMMARY_CONFIRM_HINT

    meta = dict(session.cached_prompt_meta or {})
    meta.pop("depth_hint_step_id", None)
    meta["goal_hint"] = SUMMARY_CONFIRM_HINT
    session._step_goal_hint_written = SUMMARY_CONFIRM_HINT
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])


def _store_goal_hint(session, missing: str) -> None:
    from .turn_hint import goal_hint_text

    session._debug_goal_missing = missing or ""
    meta = dict(session.cached_prompt_meta or {})
    meta.pop("depth_hint_step_id", None)
    hint = goal_hint_text(missing)
    session._step_goal_hint_written = hint
    meta["goal_hint"] = hint
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])


def _remember_check_result(session, result) -> None:
    """Keep the verdict this turn already computed. Does not call the checker again."""
    if not isinstance(result, dict):
        session._step_check_result = None
        return
    recorded = {
        "met": bool(result.get("met")),
        "missing": result.get("missing") or "",
    }
    if result.get("forced"):
        recorded["forced"] = True
    session._step_check_result = recorded


def _record_step_decision(
    session,
    agent_message,
    *,
    model_goal: bool,
    model_asks: bool,
    inferred_asks: bool,
    accepted_goal: bool,
    accepted_asks: bool,
) -> None:
    """Store this reply's step outcome on Message.usage. Other usage keys stay put."""
    if agent_message is None or not getattr(agent_message, "pk", None):
        return
    usage = agent_message.usage if isinstance(agent_message.usage, dict) else {}
    usage = dict(usage)
    usage["step_decision"] = {
        "step_no": session.current_step_no,
        "model": {
            "step_goal_met": model_goal,
            "asks_readiness": model_asks,
        },
        "inferred_asks_readiness": inferred_asks,
        "accepted": {
            "step_goal_met": accepted_goal,
            "asks_readiness": accepted_asks,
        },
        "check_done_when": getattr(session, "_step_check_result", None),
        "goal_hint": getattr(session, "_step_goal_hint_written", None),
    }
    agent_message.usage = usage
    agent_message.save(update_fields=["usage", "updated_at"])


def _downgrade_readiness(agent_message) -> None:
    if agent_message is None:
        return
    if agent_message.question_kind != Constants.QUESTION_KIND_READINESS:
        return
    agent_message.question_kind = Constants.QUESTION_KIND_OPEN
    agent_message.save(update_fields=["question_kind", "updated_at"])


def _depth_check_due(session, session_step) -> bool:
    exercise = session.exercise
    step = session_step.step
    return bool(
        exercise
        and exercise.depth_check
        and (step.completion_prompt or "").strip()
    )


def _depth_check_passed(session, session_step) -> bool:
    """First goal-met turn only. Low confidence blocks readiness and hints the next turn."""
    from ..setting.models import Setting

    from .extraction import extract_step_result

    extracted = extract_step_result(session, session_step.step)
    if not extracted:
        return True
    session_step.completion_result = extracted.get("value")
    session_step.result_confidence = extracted.get("confidence")
    session_step.save(
        update_fields=["completion_result", "result_confidence", "updated_at"]
    )
    if (extracted.get("confidence") or 0) >= Setting.get_knowledge_min_confidence():
        return True
    session._debug_depth_held = True
    meta = dict(session.cached_prompt_meta or {})
    meta["depth_hint_step_id"] = session_step.id
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    return False


def _retreat(session) -> None:
    session.state = Constants.SESSION_STATE_STEP_ACTIVE
    session.cached_prompt = None
    session.save(
        update_fields=[
            "state",
            "cached_prompt",
            "messages_no",
            "consumer_messages_no",
            "last_message",
            "updated_at",
        ]
    )


def _enter_awaiting_ready(session, agent_message, session_step) -> None:
    last = _is_last_step(session)
    if last:
        chips = [Constants.CHIP_FINISH, Constants.CHIP_NOT_YET]
        kind = Constants.SUGGESTED_RESPONSES_KIND_FINISH
    else:
        chips = [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET]
        kind = Constants.SUGGESTED_RESPONSES_KIND_READY

    agent_message.suggested_responses = chips
    agent_message.suggested_responses_kind = kind
    agent_message.question_kind = Constants.QUESTION_KIND_READINESS
    agent_message.save(
        update_fields=[
            "suggested_responses",
            "suggested_responses_kind",
            "question_kind",
            "updated_at",
        ]
    )
    session.state = Constants.SESSION_STATE_AWAITING_READY
    session.save(update_fields=["state", "updated_at"])


def _live_step(session):
    number = session.current_step_no or 0
    if number < 1:
        return None
    return (
        session.session_steps.select_related("step")
        .filter(order=number - 1)
        .first()
    )


def _is_last_step(session) -> bool:
    total = session.session_steps.count() or session.total_steps_no or 0
    return bool(total) and (session.current_step_no or 0) >= total


def _last_agent_message(session, before=None):
    from ..message.models import Message

    queryset = Message.objects.filter(session=session, sender__agent__isnull=False)
    if before is not None and before.created_at:
        queryset = queryset.filter(created_at__lt=before.created_at)
    return queryset.order_by("-created_at").first()


def _count_user_message(session, user_message) -> None:
    session.messages_no = (session.messages_no or 0) + 1
    session.consumer_messages_no = (session.consumer_messages_no or 0) + 1
    session.last_message = user_message
