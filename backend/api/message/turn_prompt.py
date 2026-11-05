"""Store the exact prompt sent for one assistant turn.

The write is off unless the ``store_turn_prompts`` setting is true. The row
hangs off the assistant message and is not part of the client message payload.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PENDING = "_pending_turn_prompt"
_DECISIONS = "_pending_turn_decisions"


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


def turn_prompts_enabled() -> bool:
    return _enabled()


def note_turn_decision(session, entry: dict) -> None:
    """Remember one decision until the assistant message is saved.

    A failure here must not affect the reply. The same type is replaced, so a
    retry keeps the decision from the call that actually answered.
    """
    try:
        if session is None or not _enabled():
            return
        rows = getattr(session, _DECISIONS, None)
        if rows is None:
            rows = []
            setattr(session, _DECISIONS, rows)
        kind = entry.get("type")
        kept = [row for row in rows if row.get("type") != kind]
        kept.append(entry)
        setattr(session, _DECISIONS, kept)
    except Exception:
        logger.exception("turn decision note failed")


def record_step_decision(message) -> None:
    """Copy the step outcome onto the prompt row. Message.usage is left as it is."""
    try:
        if message is None or not getattr(message, "id", None):
            return
        from .debug_payload import step_hold_decision
        from .models import TurnPrompt

        prompt = TurnPrompt.objects.filter(message=message).first()
        if prompt is None:
            return
        usage = message.usage if isinstance(message.usage, dict) else {}
        decision = usage.get("step_decision")
        if not isinstance(decision, dict):
            decision = None
        entry = step_hold_decision(decision)
        rows = [row for row in list(prompt.decisions or []) if row.get("type") != "step_hold"]
        rows.append(entry)
        prompt.decisions = rows
        prompt.save(update_fields=["decisions", "updated_at"])
    except Exception:
        logger.exception(
            "step decision copy failed for message=%s",
            getattr(message, "id", None),
        )


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
    decisions = list(getattr(session, _DECISIONS, None) or [])
    if hasattr(session, _DECISIONS):
        delattr(session, _DECISIONS)
    if not pending or message is None or not getattr(message, "id", None):
        return
    from .models import TurnPrompt

    pending = dict(pending)
    pending["decisions"] = decisions
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
