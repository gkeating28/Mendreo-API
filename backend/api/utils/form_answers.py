"""Store pre- and post-exercise form answers on the session and as metrics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from . import Constants
from .turn_hint import entry_quality, generic_answers_for


def decimal_answer(value) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None


def save_form_answer(session, key: str, value: str) -> None:
    """Store one answer on the session. A numeric value also inserts a metric row."""
    from ..session.models import SessionMetric

    answers = dict(session.form_answers or {})
    answers[key] = value
    session.form_answers = answers
    session.cached_prompt = None
    session.save(update_fields=["form_answers", "cached_prompt", "updated_at"])

    number = decimal_answer(value)
    if number is None:
        return

    SessionMetric.objects.create(
        consumer=session.consumer,
        exercise=session.exercise,
        session=session,
        key=key,
        value=number,
        source=Constants.SESSION_METRIC_SOURCE_FORM,
        recorded_at=timezone.now(),
    )


def record_form_answer(attribute) -> None:
    """Keyed form answer, plus a metric row when the answer is numeric."""
    question = attribute.question
    session = getattr(question, "session", None)
    if session is None:
        return

    key = (question.key or question.attribute_key or "").strip()
    if not key:
        return

    if question.type not in (
        Constants.QUESTION_TYPE_NUMBER,
        Constants.QUESTION_TYPE_SLIDER,
    ) and decimal_answer(attribute.value) is not None:
        # Non-numeric question types keep their text even if it looks like a number.
        answers = dict(session.form_answers or {})
        answers[key] = attribute.value
        session.form_answers = answers
        session.cached_prompt = None
        session.save(update_fields=["form_answers", "cached_prompt", "updated_at"])
        return

    save_form_answer(session, key, attribute.value)


def record_onboarding_knowledge(attribute) -> None:
    """Parallel knowledge write for a legacy question that points at a field."""
    from ..knowledge.services import write_knowledge_entry

    question = attribute.question
    field = getattr(question, "knowledge_field", None)
    if field is None:
        return

    confidence, review_status = entry_quality(
        attribute.value or "",
        response_type=question.type,
        generic_answers=generic_answers_for(question),
    )
    write_knowledge_entry(
        consumer=attribute.consumer,
        field=field,
        value=attribute.value or "",
        source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
        confidence=confidence,
        review_status=review_status,
        attribute=attribute,
    )
