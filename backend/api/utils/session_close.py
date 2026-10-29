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

    if getattr(session, "authoring_test", False):
        return session

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
        try:
            _update_run_summary(session)
        except Exception as exc:
            logger.warning(
                "Run summary failed for %s (%s)",
                session.id,
                type(exc).__name__,
            )
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
    queryset = Session.objects.filter(
        closed_at__isnull=True,
        authoring_test=False,
        last_message__created_at__lt=cutoff,
    )
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
            "Extract the user's answer. "
            "Extract only what the user said in their own messages. "
            "Ignore any statement about the user made in an assistant message "
            "unless the user confirmed it."
        ),
        _Extraction,
        temperature=0.1,
    )
    from .user_grounding import ground_extracted_value

    user_text = "\n".join(line[6:] for line in lines if line.startswith("User: "))
    value = ground_extracted_value((data.get("value") or "").strip(), user_text)
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
    step_results = "\n".join(results)

    from ..setting.models import Setting
    from .summary_prompts import exercise_summary_prompt

    class _Summary(BaseModel):
        detailed: str
        observations: str
        next_steps: str

    data = AI.ask(
        exercise_summary_prompt(
            Setting.get_update_exercise_summary(),
            session.consumer.user.first_name,
            check_in,
            step_results,
            summary.detailed,
        ),
        _Summary,
        temperature=0.2,
    )
    from .Agent import _summary_field_or_keep

    summary.detailed = _summary_field_or_keep(
        summary.detailed,
        data.get("detailed") or summary.detailed,
        consumer_id=summary.consumer_id,
        field_name="detailed",
    )
    summary.observations = _summary_field_or_keep(
        summary.observations,
        data.get("observations") or summary.observations,
        consumer_id=summary.consumer_id,
        field_name="observations",
    )
    summary.next_steps = _summary_field_or_keep(
        summary.next_steps,
        data.get("next_steps") or summary.next_steps,
        consumer_id=summary.consumer_id,
        field_name="next_steps",
    )
    summary.save(update_fields=["detailed", "observations", "next_steps", "updated_at"])


_TRANSCRIPT_CLIP_MESSAGES = 12
_TRANSCRIPT_CLIP_CHARS = 240


def _take_words(text: str, budget: int) -> tuple[str, int]:
    words = (text or "").split()
    if budget <= 0 or not words:
        return "", max(0, budget)
    kept = words[:budget]
    return " ".join(kept), budget - len(kept)


def shape_run_summary(data: dict | None, max_words: int) -> dict | None:
    """Cap at five bullets and keep the line plus bullets inside max_words."""
    payload = data or {}
    line = str(payload.get("line") or "").strip()
    raw_bullets = payload.get("bullets") or []
    bullets = []
    if isinstance(raw_bullets, list):
        for item in raw_bullets:
            text = str(item or "").strip()
            if text:
                bullets.append(text)
    bullets = bullets[:5]
    if not line and not bullets:
        return None
    budget = max(1, int(max_words))
    line, budget = _take_words(line, budget)
    trimmed = []
    for bullet in bullets:
        if budget <= 0:
            break
        text, budget = _take_words(bullet, budget)
        if text:
            trimmed.append(text)
    if not line and not trimmed:
        return None
    return {"line": line, "bullets": trimmed}


def _run_summary_blocked(session) -> bool:
    from ..utils import Constants

    if getattr(session, "authoring_test", False):
        return True
    if not getattr(session, "exercise_id", None):
        return True
    if not getattr(session, "completed", False):
        return True
    live = (getattr(session, "live_risk_level", None) or "").strip().lower()
    risk = (getattr(session, "risk_level", None) or "").strip().lower()
    if live == Constants.LIVE_RISK_LEVEL_HIGH:
        return True
    if risk in (Constants.RISK_LEVEL_HIGH, Constants.RISK_LEVEL_CRITICAL):
        return True
    return False


def _transcript_clip(session) -> str:
    from ..message.models import Message

    messages = list(
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("-created_at")[:_TRANSCRIPT_CLIP_MESSAGES]
    )
    messages.reverse()
    lines = []
    for message in messages:
        text = (message.text or "").strip()
        if not text:
            continue
        if len(text) > _TRANSCRIPT_CLIP_CHARS:
            text = text[:_TRANSCRIPT_CLIP_CHARS].rstrip() + "…"
        sender = getattr(message, "sender", None)
        who = "Client" if sender is not None and getattr(sender, "consumer_id", None) else "Toni"
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _run_summary_inputs(session) -> tuple[str, str, str]:
    results = []
    for row in session.session_steps.select_related("step").filter(completed=True).order_by("order"):
        title = row.step.title if row.step_id else "Step"
        results.append(f"{title}: {row.completion_result or ''}")
    return (
        session.pre_exercise_prompt_summary or "",
        "\n".join(results),
        _transcript_clip(session),
    )


def _update_run_summary(session) -> None:
    from pydantic import BaseModel

    from ..setting.models import Setting
    from .AI import AI
    from .summary_prompts import run_summary_prompt

    if _run_summary_blocked(session):
        return

    class _RunSummary(BaseModel):
        line: str
        bullets: list[str]

    check_in, step_results, transcript = _run_summary_inputs(session)
    name = session.consumer.user.first_name
    data = AI.ask(
        run_summary_prompt(
            Setting.get_run_summary_prompt(),
            name,
            Setting.get_run_summary_tone_guide(),
            Setting.get_run_summary_max_length(),
            check_in,
            step_results,
            transcript,
        ),
        _RunSummary,
        temperature=0.2,
    )
    shaped = shape_run_summary(data, Setting.get_run_summary_max_length())
    if not shaped:
        return
    session.run_summary = shaped
    session.save(update_fields=["run_summary", "updated_at"])
