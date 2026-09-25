"""Exercise session transitions. Active only when AI_STATE_MACHINE_ENABLED is on.

Code owns the step. The model reports step_goal_met and asks_readiness.
Chip taps do not call the chat model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from . import Constants


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
    r"^(yes, i['’]m ready|not yet|finish exercise|ready to proceed|i['’]m ready for the next step)[.!]?$",
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
        if not _MODEL_READY_CHIPS.match(str(chip).strip())
    ]
    return question_kind, kept


def on_model_turn(session, agent_message, response) -> None:
    """Apply asks_readiness / step_goal_met after the agent message is saved."""
    if session.in_pre_exercise_phase():
        return

    if session.state == Constants.SESSION_STATE_CHECK_IN:
        session.state = Constants.SESSION_STATE_STEP_ACTIVE
        session.save(update_fields=["state", "updated_at"])

    session_step = _live_step(session)
    goal_met = bool(getattr(response, "step_goal_met", False))
    asks = bool(getattr(response, "asks_readiness", False))

    if session_step and goal_met and session_step.goal_met_at is None:
        if _depth_check_due(session, session_step):
            if not _depth_check_passed(session, session_step):
                asks = False
                if agent_message is not None and agent_message.question_kind == Constants.QUESTION_KIND_READINESS:
                    agent_message.question_kind = Constants.QUESTION_KIND_OPEN
                    agent_message.save(update_fields=["question_kind", "updated_at"])
        session_step.goal_met_at = timezone.now()
        session_step.save(update_fields=["goal_met_at", "updated_at"])

    if not asks or session_step is None or session_step.goal_met_at is None:
        return

    _enter_awaiting_ready(session, agent_message, session_step)


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


_READY_AFFIRMATIONS = {
    "yes",
    "yes please",
    "yeah",
    "yep",
    "ok",
    "okay",
    "sure",
    "ready",
    "i'm ready",
    "i am ready",
    "im ready",
    "yes i'm ready",
    "yes, i'm ready",
    "let's go",
    "lets go",
}


def is_ready_affirmation(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().replace("\u2019", "'").split())
    return normalized.rstrip(".!") in _READY_AFFIRMATIONS


def handle_typed_while_awaiting(user_message) -> ChipOutcome | None:
    """A typed reply while waiting for readiness does not call the chat model.

    A plain yes confirms the step. Anything else returns to the live step.
    """
    session = user_message.session
    if session.state != Constants.SESSION_STATE_AWAITING_READY:
        return None
    if is_ready_affirmation(user_message.text or ""):
        return _confirm(session, user_message)
    _count_user_message(session, user_message)
    _retreat(session)
    return ChipOutcome(user_message, build_session_state(session))


def opening_turn(step_no: int) -> str:
    """Hidden user turn that opens a step. It is not shown in the chat.

    "Begin step N" makes the model write a welcome. This tells it the
    exercise is already underway and to ask the step's first question.
    """
    if step_no <= 1:
        return (
            "The exercise has already been introduced during the check-in. "
            "Ask the first question of step 1 now. "
            "Do not welcome the user, explain the exercise, or ask if it is right for them."
        )
    return (
        f"Continue straight into step {step_no}. "
        "Ask only the first question that step's instructions require. "
        "Do not introduce the exercise."
    )


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
    title = (step.success_title if step else None) or "Well Done!"

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
        Exercise.all_objects.filter(id=session.exercise_id).update(
            completions_no=F("completions_no") + 1
        )
    else:
        session.state = Constants.SESSION_STATE_STEP_ACTIVE
        session.current_step_no = step_no + 1
        session.save(
            update_fields=[
                "state",
                "current_step_no",
                "cached_prompt",
                "messages_no",
                "consumer_messages_no",
                "last_message",
                "updated_at",
            ]
        )
        greeting = request_session_greeting(
            session,
            synthetic_text=opening_turn(step_no + 1),
        )

    card = {"title": title, "label": label or ""}
    display = greeting or user_message
    return ChipOutcome(display, build_session_state(session, completion_card=card))


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
