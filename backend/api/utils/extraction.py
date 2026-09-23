"""One-shot step result extraction. The chat model is not used here."""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import Constants
from .AI import AI


class _Extraction(BaseModel):
    value: str = Field(description="The user's result for this step, in their words")
    confidence: float = Field(description="Confidence from 0 to 1")


def extract_step_result(session, step) -> dict | None:
    """Return ``{value, confidence}`` or None when the step has no completion prompt."""
    prompt_text = (getattr(step, "completion_prompt", None) or "").strip()
    if not prompt_text:
        return None

    transcript = _step_transcript(session, step)
    data = AI.ask(
        (
            f"{prompt_text}\n\n"
            "Transcript of this step:\n"
            f"{transcript or '(no messages)'}\n\n"
            "Extract the user's result for this step."
        ),
        _Extraction,
        temperature=0.1,
    )
    value = (data.get("value") or "").strip() or None
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))

    if value and getattr(step, "result_field_id", None):
        _write_result_knowledge(session, step, value, confidence)

    return {"value": value, "confidence": confidence}


def _step_transcript(session, step) -> str:
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

    messages = Message.objects.filter(session=session).select_related("sender").order_by("created_at")
    if boundary is not None:
        messages = messages.filter(created_at__gt=boundary)

    lines = []
    for message in messages:
        who = "User" if message.sender_id and message.sender.consumer_id else "Assistant"
        text = (message.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _write_result_knowledge(session, step, value: str, confidence: float) -> None:
    from ..knowledge.services import write_knowledge_entry
    from ..setting.models import Setting

    review = Constants.KNOWLEDGE_REVIEW_ACCEPTED
    if confidence < Setting.get_knowledge_min_confidence():
        review = Constants.KNOWLEDGE_REVIEW_PENDING
    write_knowledge_entry(
        consumer=session.consumer,
        field=step.result_field,
        value=value,
        source=Constants.KNOWLEDGE_ENTRY_SOURCE_EXERCISE,
        confidence=confidence,
        review_status=review,
        session=session,
    )
