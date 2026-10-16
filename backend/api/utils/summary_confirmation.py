"""A step that must name the worry cannot finish before the user agrees the summary."""

from __future__ import annotations

import re

_REQUIRED = re.compile(
    r"confirm(?:ed|s|ing)?\s+(?:that\s+)?(?:the\s+)?summary|summary\s+is\s+accurate",
    re.IGNORECASE,
)

_ASK = re.compile(
    r"\b(?:did i (?:get|capture|understand)|have i got|does that (?:sound|seem) right|"
    r"is that (?:right|accurate|correct)|did i (?:get|have) (?:that|it) right)\b",
    re.IGNORECASE,
)


def summary_confirmation_required(done_when: str) -> bool:
    return bool(_REQUIRED.search(done_when or ""))


def summary_confirmation_rule(done_when: str) -> str:
    if not summary_confirmation_required(done_when):
        return ""
    return (
        "\n\nBefore this step can finish, one message must summarise the worry "
        "and the situation in the user's words and ask if that summary is right. "
        "Do not set step_goal_met on that message. "
        "Do not ask if they are ready for the next step until they have confirmed the summary."
    )


def is_summary_confirmation(text: str) -> bool:
    """A recap that names what was said and asks if it is right.

    A short question, or a readiness question, does not count.
    """
    raw = " ".join((text or "").split())
    if len(raw.split()) < 12:
        return False
    return bool(_ASK.search(raw))


def summary_was_confirmed(session, step) -> bool:
    """True when the user agreed after an assistant summary in this step."""
    from .SessionStateMachine import is_ready_affirmation

    pending = False
    for message in _step_messages(session, step):
        text = message.text or ""
        is_user = bool(getattr(message.sender, "consumer_id", None))
        if not is_user and is_summary_confirmation(text):
            pending = True
            continue
        if is_user and pending and is_ready_affirmation(text):
            return True
        if is_user:
            pending = False
    return False


def _step_messages(session, step):
    from ..message.models import Message

    boundary = None
    previous = (
        session.session_steps.filter(order__lt=step.order, completed=True)
        .order_by("-order")
        .first()
    )
    if previous is not None:
        boundary = previous.updated_at
    elif session.pre_exercise_completed_at:
        boundary = session.pre_exercise_completed_at

    messages = (
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("created_at")
    )
    if boundary is not None:
        messages = messages.filter(created_at__gt=boundary)
    return messages
