"""Pick at most one knowledge question for the live prompt."""

from __future__ import annotations

from django.conf import settings

from ..utils import Constants


def assign_pending_question(session) -> str:
    """Return a <PENDING_QUESTION> block, or empty. Records the question on the session."""
    if session.pending_knowledge_question_id:
        return _block(session.pending_knowledge_question, session)

    flow = _flow_for(session)
    if not flow:
        return ""
    question = _select(session, flow)
    if question is None:
        return ""
    session.pending_knowledge_question = question
    session.save(update_fields=["pending_knowledge_question", "updated_at"])
    return _block(question, session)


def _flow_for(session) -> str | None:
    if not session.exercise_id:
        return Constants.KNOWLEDGE_FLOW_GENERAL_CHAT
    if session.in_pre_exercise_phase():
        return f"check_in:{session.exercise_id}"
    return None


def _select(session, flow: str):
    from ..knowledge.models import KnowledgeEntry, KnowledgeQuestion

    consumer = session.consumer
    session_count = consumer.sessions.count()
    questions = KnowledgeQuestion.objects.filter(active=True).select_related("target_field")
    ranked = []
    for question in questions:
        if flow not in (question.flows or []):
            continue
        if not _trigger_met(question, session, session_count):
            continue
        if _already_answered(consumer, question):
            continue
        ranked.append((question.order_for_flow(flow), question.order, question.id, question))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def _trigger_met(question, session, session_count: int) -> bool:
    trigger = question.trigger
    if trigger == Constants.KNOWLEDGE_TRIGGER_FIRST_SESSION:
        return session_count <= 1
    if trigger == Constants.KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS:
        try:
            needed = int((question.trigger_config or {}).get("n") or 0)
        except (TypeError, ValueError):
            return False
        return session_count >= needed
    if trigger == Constants.KNOWLEDGE_TRIGGER_ON_EXERCISE_COMPLETION:
        from ..session.models import Session

        return Session.objects.filter(
            consumer=session.consumer,
            exercise_id=session.exercise_id,
            completed=True,
        ).exists()
    return False


def _already_answered(consumer, question) -> bool:
    from ..knowledge.models import KnowledgeEntry

    entries = KnowledgeEntry.objects.filter(consumer=consumer, field_id=question.target_field_id)
    accepted = entries.filter(review_status=Constants.KNOWLEDGE_REVIEW_ACCEPTED).exists()
    if accepted:
        return True
    pending = list(
        entries.filter(review_status=Constants.KNOWLEDGE_REVIEW_PENDING).values_list("source", flat=True)
    )
    if pending and set(pending) == {Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING}:
        return False
    return bool(pending)


def _block(question, session) -> str:
    from ..knowledge.models import KnowledgeEntry

    earlier = (
        KnowledgeEntry.objects.filter(
            consumer=session.consumer,
            field_id=question.target_field_id,
            review_status=Constants.KNOWLEDGE_REVIEW_PENDING,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
        )
        .order_by("-created_at")
        .first()
    )
    follow = ""
    if earlier is not None:
        follow = (
            f"\nThey said '{earlier.value}' at sign-up. "
            f"{question.follow_up_prompt or 'Ask what a good day and a hard day look like.'}"
        )
    return (
        "<PENDING_QUESTION>\n"
        f"{question.prompt}\n"
        "Ask this when it fits the conversation. One question only."
        f"{follow}\n"
        "</PENDING_QUESTION>"
    )
