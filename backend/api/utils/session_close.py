"""Session close: rating, knowledge extraction, exercise summary. Flag-gated."""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return True


def close_session(session, reason: str):
    """Close once. A second call does not rate or extract again."""
    if not enabled() or session.closed_at:
        return session

    session.closed_at = timezone.now()
    session.close_reason = reason
    session.save(
        update_fields=["closed_at", "close_reason", "completed", "completed_at", "updated_at"]
    )

    try:
        _rate(session)
    except Exception:
        logger.exception("Session rating failed for %s", session.id)
    try:
        _extract_pending_question(session)
    except Exception:
        logger.exception("Knowledge extraction failed for %s", session.id)
    if session.completed or reason == "completed":
        try:
            _update_exercise_summary(session)
        except Exception:
            logger.exception("Exercise summary failed for %s", session.id)
    return session


def close_idle_sessions() -> int:
    from datetime import timedelta

    from ..session.models import Session
    from ..setting.models import Setting

    if not enabled():
        return 0
    minutes = Setting.get_session_inactivity_minutes()
    cutoff = timezone.now() - timedelta(minutes=minutes)
    closed = 0
    queryset = Session.objects.filter(closed_at__isnull=True, last_message__created_at__lt=cutoff)
    for session in queryset.iterator():
        close_session(session, "inactivity")
        closed += 1
    return closed


def _rate(session) -> None:
    from ..message.models import Message
    from ..summary.models import Summary
    from .Agent import _format_session, build_session_prompt, update_session

    messages = list(
        Message.objects.filter(session=session).select_related("sender").order_by("created_at")
    )
    if not messages:
        return
    summary = Summary.get_or_create(session.consumer)
    name = session.consumer.user.first_name
    lines = _format_session(session=session, user_first_name=name, messages=messages)
    prompt = build_session_prompt(lines, summary, name)
    update_session(prompt, session)


def _extract_pending_question(session) -> None:
    from ..knowledge.services import write_knowledge_entry
    from ..message.models import Message
    from ..setting.models import Setting
    from ..utils import Constants
    from .AI import AI
    from .extraction import _Extraction

    question = session.pending_knowledge_question
    if question is None or not (question.extraction_prompt or "").strip():
        return
    lines = []
    for message in Message.objects.filter(session=session).select_related("sender").order_by("created_at"):
        who = "User" if message.sender_id and message.sender.consumer_id else "Assistant"
        text = (message.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    data = AI.ask(
        (
            f"{question.extraction_prompt.strip()}\n\n"
            f"Transcript:\n{chr(10).join(lines) or '(no messages)'}\n\n"
            "Extract the user's answer."
        ),
        _Extraction,
        temperature=0.1,
    )
    value = (data.get("value") or "").strip()
    if not value:
        return
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    review = Constants.KNOWLEDGE_REVIEW_ACCEPTED
    if confidence < Setting.get_knowledge_min_confidence():
        review = Constants.KNOWLEDGE_REVIEW_PENDING
    write_knowledge_entry(
        consumer=session.consumer,
        field=question.target_field,
        value=value,
        source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        confidence=confidence,
        review_status=review,
        knowledge_question=question,
        session=session,
    )
    if review == Constants.KNOWLEDGE_REVIEW_ACCEPTED:
        from ..knowledge.models import KnowledgeEntry

        KnowledgeEntry.objects.filter(
            consumer=session.consumer,
            field=question.target_field,
            review_status=Constants.KNOWLEDGE_REVIEW_PENDING,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
        ).update(review_status=Constants.KNOWLEDGE_REVIEW_REJECTED)


def _update_exercise_summary(session) -> None:
    from pydantic import BaseModel, Field

    from ..exercise_summary.models import ExerciseSummary
    from .AI import AI

    if not session.exercise_id:
        return
    summary = ExerciseSummary.get_or_create(session.consumer, session.exercise)
    results = []
    for row in session.session_steps.select_related("step").filter(completed=True).order_by("order"):
        results.append(f"{row.step.title}: {row.completion_result or ''}")
    check_in = session.pre_exercise_prompt_summary or ""

    class _Summary(BaseModel):
        detailed: str
        observations: str
        next_steps: str

    data = AI.ask(
        (
            "Update the notes for this exercise from the check-in and the step results.\n\n"
            f"Check-in summary:\n{check_in or '(none)'}\n\n"
            f"Step results:\n{chr(10).join(results) or '(none)'}\n\n"
            f"Previous notes:\n{summary.detailed or ''}"
        ),
        _Summary,
        temperature=0.2,
    )
    summary.detailed = data.get("detailed") or summary.detailed
    summary.observations = data.get("observations") or summary.observations
    summary.next_steps = data.get("next_steps") or summary.next_steps
    summary.save(update_fields=["detailed", "observations", "next_steps", "updated_at"])
