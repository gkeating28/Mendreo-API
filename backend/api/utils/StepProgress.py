"""Honor exercise step-complete only after an explicit next-step readiness ask."""

from __future__ import annotations

import re
from typing import Optional, Tuple

_GATE = re.compile(
    r"(?:"
    r"are you ready to (?:progress|continue|move on)"
    r"|(?:shall|should) we (?:move on|continue|proceed)"
    r"|move on to (?:the )?(?:next|final|last) step"
    r"|move onto (?:the )?(?:next|final|last) step"
    r"|(?:progress|continue) to (?:the )?(?:next|final|last) step"
    r"|ready to progress"
    r"|ready to move on"
    r")",
    re.IGNORECASE,
)

_PROCEED_ONLY = re.compile(
    r"are you ready to proceed\b",
    re.IGNORECASE,
)

_CONFIRM = re.compile(
    r"^(?:"
    r"yes\b.*"
    r"|yeah|yep|yup|ok|okay|sure"
    r"|(?:i(?:'?m| am) )?ready(?: to (?:continue|progress|move on)(?: to (?:the )?(?:next|final|last) step)?)?"
    r"|let'?s (?:go|continue|move on|progress)"
    r")\.?$",
    re.IGNORECASE,
)


def _normalize(text: Optional[str]) -> str:
    return (
        (text or "")
        .replace("\u2019", "'")
        .replace("\u2018", "'")
        .strip()
    )


def is_advance_gate_text(text: Optional[str]) -> bool:
    """True when Toni is asking to leave this step for the next one."""
    raw = _normalize(text)
    if not raw:
        return False
    if _PROCEED_ONLY.search(raw) and not re.search(
        r"\b(next|final|last) step\b", raw, re.IGNORECASE
    ):
        # Think Flexibly step 1: "ready to proceed" after naming the thought
        # is still this step (judgmental-error work follows).
        return False
    return bool(_GATE.search(raw))


def is_progress_confirm_text(text: Optional[str]) -> bool:
    t = _normalize(text)
    if not t:
        return False
    return bool(_CONFIRM.match(t))


def last_agent_text_for_session(session) -> str:
    from ..message.models import Message

    text = (
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("-created_at")
        .values_list("text", flat=True)
        .first()
    )
    return text or ""


def resolve_step_progress(
    *,
    current_step_no: int,
    total_steps_no: int,
    tagged_step_no: Optional[int],
    is_step_complete: bool,
    agent_text: str,
    user_text: str,
    last_agent_text: str,
    is_skip: bool = False,
) -> Tuple[int, bool]:
    """
    Keep the session on the current step until the user has confirmed a
    dedicated next-step readiness ask. Never force-complete just because the
    model incremented step_no (Think Flexibly often does that after "move on"
    in the step instructions).
    """
    current = max(1, current_step_no or 1)
    total = max(0, total_steps_no or 0)

    if is_skip:
        return current, True

    complete = bool(is_step_complete)

    if complete and is_advance_gate_text(agent_text):
        complete = False

    if complete and total and current < total:
        if not (
            is_advance_gate_text(last_agent_text)
            and is_progress_confirm_text(user_text)
        ):
            complete = False

    return current, complete
