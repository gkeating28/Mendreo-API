"""Whose risk a high turn is about. Only self_now closes the chat.

The model call uses the same AI.ask path as the other short checks.
A failure, a timeout, or an invalid verdict stays high.
"""

from __future__ import annotations

import logging
import threading
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# The turn waits this long, then stays high. The HTTP client uses the same limit.
RISK_CHECK_TIMEOUT_SECONDS = 15
RISK_CHECK_TIMEOUT_MS = 15_000
_CONTEXT_MESSAGES = 6
_REASON_MAX = 240

ABOUT_SELF_NOW = "self_now"
ABOUT_SELF_PAST = "self_past"
ABOUT_OTHER_PERSON = "other_person"
ABOUT_FIGURE_OF_SPEECH = "figure_of_speech"
ABOUT_TOPIC_ONLY = "topic_only"
ABOUT_UNCLEAR = "unclear"

RISK_CHECK_ABOUTS = (
    ABOUT_SELF_NOW,
    ABOUT_SELF_PAST,
    ABOUT_OTHER_PERSON,
    ABOUT_FIGURE_OF_SPEECH,
    ABOUT_TOPIC_ONLY,
    ABOUT_UNCLEAR,
)

# A therapist will review this wording.
RISK_CHECK_INSTRUCTIONS = """
You are checking one message in a support chat. Decide whose risk it is.
Read the latest user message in light of the recent messages. Judge the latest message.

about must be exactly one of:

self_now
The person is expressing thoughts of suicide or self-harm about themselves in the present, or saying they intend to do it.
Examples: "I'm going to kill myself tonight", "I've been thinking about ending my life", "I want to die", "I can't do this anymore, I want to die".

self_past
The person is referring to their own past thoughts or attempts, not a present intention.
Examples: "I tried to end my life last year", "I used to want to die".

other_person
The risk is about a friend, family member, or someone else, not the speaker's own present risk.
Examples: "My friend is suicidal", "my friend died by suicide last year".

figure_of_speech
An idiom or exaggeration, not a real statement of risk.
Examples: "I could kill myself for forgetting my keys", "I'm so embarrassed I want to die".

topic_only
The subject comes up in general, in the news, in fiction, or in study, without the speaker's own risk.
Examples: "I read an article about suicide".

unclear
You cannot tell whose risk it is, or whether it is present.

When you are in doubt between self_now and anything else, choose self_now or unclear.
reason is one short sentence explaining the choice. Do not quote the user's message.
""".strip()


class RiskCheckVerdict(BaseModel):
    about: Literal[
        "self_now",
        "self_past",
        "other_person",
        "figure_of_speech",
        "topic_only",
        "unclear",
    ] = Field(
        description=(
            "Whose risk the latest user message is. "
            "self_now, self_past, other_person, figure_of_speech, topic_only, or unclear."
        )
    )
    reason: str = Field(description="One short sentence. Do not quote the user.")


def build_risk_check_prompt(user_text: str, context_lines: list[str] | None) -> str:
    """Instructions, the last few turns, and the latest user message."""
    context = "\n".join(context_lines or []) or "(none)"
    return (
        f"{RISK_CHECK_INSTRUCTIONS}\n\n"
        "Recent messages:\n"
        f"{context}\n\n"
        "Latest user message:\n"
        f"{user_text or ''}"
    )


def _fail(session_id, error: str) -> dict:
    logger.warning("risk check failed session=%s error=%s", session_id, error)
    return {
        "about": ABOUT_SELF_NOW,
        "reason": "The check could not be completed.",
    }


def _ask(prompt: str) -> dict:
    from django.db import close_old_connections

    from .AI import AI

    close_old_connections()
    try:
        return AI.ask(
            prompt,
            RiskCheckVerdict,
            temperature=0.1,
            timeout_ms=RISK_CHECK_TIMEOUT_MS,
        )
    finally:
        close_old_connections()


def _call_model(prompt: str, session_id):
    """Return (data, error). The turn stops waiting after the timeout."""
    box: dict = {}

    def _run():
        try:
            box["data"] = _ask(prompt)
        except Exception as exc:  # noqa: BLE001 - fail safe to high
            box["error"] = type(exc).__name__

    # Daemon so a slow provider cannot hold the process after the turn has moved on.
    thread = threading.Thread(target=_run, name="risk-check", daemon=True)
    thread.start()
    thread.join(RISK_CHECK_TIMEOUT_SECONDS)
    if thread.is_alive():
        return None, "timeout"
    if box.get("error"):
        return None, box["error"]
    return box.get("data"), None


def classify_risk(user_text: str, context_lines: list[str] | None = None, *, session_id=None) -> dict:
    """Ask whose risk the latest message is. Failures come back as self_now."""
    data, error = _call_model(build_risk_check_prompt(user_text, context_lines), session_id)
    if error:
        return _fail(session_id, error)
    if not isinstance(data, dict):
        return _fail(session_id, "invalid")
    about = str(data.get("about") or "").strip()
    if about not in RISK_CHECK_ABOUTS:
        return _fail(session_id, "invalid")
    reason = str(data.get("reason") or "").strip()[:_REASON_MAX] or "No reason given."
    logger.info("risk check session=%s about=%s", session_id, about)
    return {"about": about, "reason": reason}


def _context_lines(session, user_text: str) -> list[str]:
    """Up to six messages before the latest user message, oldest first."""
    from ..message.models import Message

    rows = list(
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("-created_at", "-id")[: _CONTEXT_MESSAGES + 1]
    )
    if rows:
        newest = rows[0]
        sender = newest.sender
        is_user = bool(sender and sender.consumer_id)
        if is_user and (newest.text or "").strip() == (user_text or "").strip():
            rows = rows[1:]
    rows = list(reversed(rows[:_CONTEXT_MESSAGES]))
    lines = []
    for row in rows:
        sender = row.sender
        who = "User" if sender and sender.consumer_id else "Toni"
        text = (row.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return lines


def check_whose_risk(session, user_text: str) -> dict:
    """Latest message plus the last six turns. See classify_risk."""
    return classify_risk(
        user_text,
        _context_lines(session, user_text),
        session_id=getattr(session, "id", None),
    )
