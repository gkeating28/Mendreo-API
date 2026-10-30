"""A step that requires a confirmed summary cannot finish before the user agrees."""

from __future__ import annotations

import re

_REQUIRED = re.compile(
    r"(?:confirm(?:ed|s|ing)?|agree(?:d|s)?)\s+(?:with\s+)?(?:that\s+)?(?:the\s+)?summary"
    r"|summary\s+is\s+accurate",
    re.IGNORECASE,
)

_ASK = re.compile(
    r"\b(?:did i (?:get|capture|understand)|have i got|"
    r"does that (?:sound|seem) right|does this (?:plan |summary )?sound right|"
    r"does this summary accurately reflect|"
    r"is that (?:right|accurate|correct)|is this right|"
    r"did i (?:get|have) (?:that|it) right|does that cover it)\b",
    re.IGNORECASE,
)

_SUMMARY_AFFIRM_START = re.compile(
    r"^(?:yes|yeah|yep|correct|right|exactly|that's right|that's correct|"
    r"that covers it|sounds good|looks good|perfect)\b",
    re.IGNORECASE,
)
_SUMMARY_AFFIRM_BLOCK = re.compile(
    r"\b(?:no|not|but|except|change|wrong)\b",
    re.IGNORECASE,
)


def summary_confirmation_required(done_when: str) -> bool:
    return bool(_REQUIRED.search(done_when or ""))


def summary_confirmation_rule(done_when: str) -> str:
    if not summary_confirmation_required(done_when):
        return ""
    return (
        "\n\nBefore this step can finish, one message must summarise what this step "
        "asked for, in the user's words, and ask if that summary is right. "
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


def is_summary_affirmation(text: str) -> bool:
    """A short agreement after a summary. Used only by summary_was_confirmed."""
    from .SessionStateMachine import is_ready_affirmation

    if is_ready_affirmation(text):
        return True
    raw = " ".join(
        (text or "").strip().lower().replace("\u2019", "'").replace("\u2018", "'").split()
    ).rstrip(".!")
    words = raw.split()
    if not words or len(words) > 10:
        return False
    if _SUMMARY_AFFIRM_BLOCK.search(raw):
        return False
    return bool(_SUMMARY_AFFIRM_START.match(raw))


def summary_was_confirmed(session, step) -> bool:
    """True when the user agreed after an assistant summary in this step."""
    from .SessionStateMachine import _is_last_step, is_ready_affirmation

    agreed = is_summary_affirmation if _is_last_step(session) else is_ready_affirmation
    pending = False
    for message in _step_messages(session, step):
        text = message.text or ""
        is_user = bool(getattr(message.sender, "consumer_id", None))
        if not is_user and is_summary_confirmation(text):
            pending = True
            continue
        if is_user and pending and agreed(text):
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
