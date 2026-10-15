"""Store the exact prompt sent for one assistant turn.

The write is off unless the ``store_turn_prompts`` setting is true. The row
hangs off the assistant message and is not part of the client message payload.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PENDING = "_pending_turn_prompt"


def history_rows(history) -> list[dict]:
    """Role and text for each model message, in send order."""
    rows = []
    for item in history or []:
        parts = getattr(item, "parts", None) or []
        text = "\n".join(
            piece for piece in (_part_text(part) for part in parts) if piece
        )
        role = "assistant" if type(item).__name__ == "ModelResponse" else "user"
        rows.append({"role": role, "text": text})
    return rows


def stash_turn_prompt(session, *, model_name: str, system_prompt: str, user_prompt: str, history) -> None:
    """Remember this call's payload until the assistant message is saved."""
    if not _enabled():
        if hasattr(session, _PENDING):
            delattr(session, _PENDING)
        return
    setattr(
        session,
        _PENDING,
        {
            "model_name": (model_name or "")[:255],
            "system_prompt": system_prompt or "",
            "user_prompt": user_prompt or "",
            "history": history_rows(history),
        },
    )


def save_pending_turn_prompt(session, message) -> None:
    """Persist the stashed payload on the assistant message. Failures stay logged."""
    pending = getattr(session, _PENDING, None)
    if hasattr(session, _PENDING):
        delattr(session, _PENDING)
    if not pending or message is None or not getattr(message, "id", None):
        return
    from .models import TurnPrompt

    try:
        TurnPrompt.objects.create(message=message, **pending)
    except Exception:
        logger.exception(
            "turn prompt save failed for message=%s",
            getattr(message, "id", None),
        )


def _enabled() -> bool:
    try:
        from ..setting.models import Setting

        return Setting.get_store_turn_prompts()
    except Exception:
        logger.exception("turn prompt setting lookup failed")
        return False


def _part_text(part) -> str:
    content = getattr(part, "content", None)
    if isinstance(content, str):
        return content
    return ""
