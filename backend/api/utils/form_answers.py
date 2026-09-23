"""Store pre- and post-exercise form answers on the session and as metrics."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone

from . import Constants
from .turn_hint import entry_quality, generic_answers_for


def record_form_answer(attribute) -> None:
    """Keyed form answer, plus a metric row when the answer is numeric."""
    from ..session.models import SessionMetric

    question = attribute.question
    session = getattr(question, "session", None)
    if session is None:
        return

    key = (question.key or question.attribute_key or "").strip()
    if not key:
        return

    answers = dict(session.form_answers or {})
    answers[key] = attribute.value
    session.form_answers = answers
    session.cached_prompt = None
    session.save(update_fields=["form_answers", "cached_prompt", "updated_at"])

    if question.type not in (
        Constants.QUESTION_TYPE_NUMBER,
        Constants.QUESTION_TYPE_SLIDER,
    ):
        return

    try:
        number = Decimal(str(attribute.value).strip())
    except (InvalidOperation, AttributeError):
        return

    SessionMetric.objects.create(
        consumer=attribute.consumer,
        exercise=session.exercise,
        session=session,
        key=key,
        value=number,
        source=Constants.SESSION_METRIC_SOURCE_FORM,
        recorded_at=timezone.now(),
    )


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
