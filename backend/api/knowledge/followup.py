"""First-chat re-ask of vague initial free-text onboarding answers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from django.utils import timezone
from pydantic import BaseModel, Field

from ..utils import Constants

logger = logging.getLogger(__name__)


class VaguenessClassification(BaseModel):
    is_vague: bool = Field(
        description=(
            "True when the answer is generic, vague, or a non-answer "
            "(e.g. 'fine', 'okay', 'idk', 'stuff', 'the usual'). "
            "False when it names a concrete situation, habit, person, feeling, or event."
        )
    )
    reasoning: str = Field(default="", description="Short justification")


@dataclass
class FollowupReply:
    """Result of handling a user turn against an active onboarding follow-up."""

    canned_text: str | None = None


def should_classify_onboarding_answer(*, variant: str, response_type: str, classify: bool) -> bool:
    return (
        bool(classify)
        and variant == Constants.KNOWLEDGE_FLOW_INITIAL
        and response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT
    )


# Obvious non-answers. Used at onboarding complete so we never block that
# request on Gemini (the last step used to wait on one LLM call per free-text
# answer, inside the DB transaction).
_VAGUE_ANSWER_PHRASES = frozenset(
    {
        "fine",
        "ok",
        "okay",
        "alright",
        "all right",
        "good",
        "great",
        "idk",
        "i dont know",
        "dont know",
        "not sure",
        "unsure",
        "no idea",
        "nothing",
        "nothing much",
        "not much",
        "nothing really",
        "n a",
        "na",
        "none",
        "nil",
        "meh",
        "whatever",
        "same",
        "the usual",
        "usual",
        "normal",
        "stuff",
        "things",
        "it is what it is",
        "all good",
        "im fine",
        "im ok",
        "im okay",
    }
)


def _normalize_answer(answer: str) -> str:
    cleaned = (answer or "").strip().lower().replace("'", "")
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def looks_vague(answer: str) -> bool:
    """True for short generic non-answers. Fail-open (False) when unsure."""
    normalized = _normalize_answer(answer)
    return bool(normalized) and normalized in _VAGUE_ANSWER_PHRASES


def flag_onboarding_answer_for_followup(
    question_prompt: str,
    answer: str,
    *,
    suggested_responses: list[str] | None = None,
) -> bool:
    """
    Whether to re-ask this initial free-text answer in the first chat.

    Instant: chip taps and obvious platitudes only. Gemini stays on the
    in-chat follow-up path so completing onboarding is not blocked.
    """
    text = (answer or "").strip()
    if not text:
        return False
    if suggested_responses and text in suggested_responses:
        return False
    return looks_vague(text)


def is_answer_vague(question_prompt: str, answer: str) -> bool:
    """
    True when Gemini classifies the answer as vague/generic.

    Fail-open: on error or empty input, treat as specific (do not flag).
    """
    text = (answer or "").strip()
    prompt = (question_prompt or "").strip()
    if not text:
        return False

    from ..utils.AI import AI

    instruction = (
        "You classify whether a user's onboarding answer is specific enough to keep "
        "in a personal profile, or too vague/generic to be useful.\n\n"
        f"Question:\n{prompt or '(no question provided)'}\n\n"
        f"Answer:\n{text}\n\n"
        "Vague/generic: 'fine', 'okay', 'idk', 'stuff', 'not sure', 'the usual', "
        "one-word non-answers, empty platitudes, or anything that does not add "
        "meaningful personal detail.\n"
        "Specific: names a situation, person, habit, feeling with context, or a "
        "concrete event.\n"
        "Return is_vague=true only when the answer is not specific enough."
    )
    try:
        result = AI.ask(instruction, VaguenessClassification, temperature=0.1)
    except Exception:
        logger.exception("Vagueness classification failed; treating answer as specific")
        return False

    return bool(result.get("is_vague"))


def is_onboarding_followup_session(session) -> bool:
    """True for the general session that claimed the one-shot follow-up latch."""
    if getattr(session, "exercise_id", None):
        return False
    consumer = getattr(session, "consumer", None)
    if consumer is None:
        return False
    consumed = getattr(consumer, "onboarding_followup_consumed_at", None)
    if not consumed:
        return False
    created = getattr(session, "created_at", None)
    if created is None:
        return True
    return created <= consumed


def _invalidate_session_prompt(session) -> None:
    if session is None:
        return
    if not getattr(session, "cached_prompt", None):
        return
    session.cached_prompt = None
    session.save(update_fields=["cached_prompt", "updated_at"])


def _save_followup_state(entry, **fields) -> None:
    for key, value in fields.items():
        setattr(entry, key, value)
    update_fields = list(fields.keys()) + ["updated_at"]
    entry.save(update_fields=update_fields)


def activate_next_followup(consumer, session=None):
    """Mark the oldest pending entry as asked (attempt 1) and return it."""
    from .models import KnowledgeEntry

    pending = KnowledgeEntry.pending_followups_for(consumer)
    if not pending:
        return None
    entry = pending[0]
    if entry.followup_attempts < 1:
        _save_followup_state(entry, followup_attempts=1)
        _invalidate_session_prompt(session)
    return entry


def _clear_followup(entry, session=None) -> None:
    _save_followup_state(entry, needs_followup=False)
    _invalidate_session_prompt(session)


def _write_improved_answer(entry, *, value: str, session) -> None:
    from .services import write_knowledge_entry

    write_knowledge_entry(
        consumer=entry.consumer,
        field=entry.field,
        value=value,
        source=Constants.KNOWLEDGE_ENTRY_SOURCE_AI,
        knowledge_question=entry.knowledge_question,
        session=session,
        confidence=1.0,
        needs_followup=False,
        followup_attempts=0,
        followup_prompt="",
    )
    _clear_followup(entry, session=session)


def greeting_user_prompt_for_session(session) -> str | None:
    """Activate the first pending flag and return the synthetic opener prompt."""
    entry = activate_next_followup(session.consumer, session)
    if entry is None:
        return None
    question = (entry.followup_prompt or "").strip() or (
        entry.knowledge_question.prompt if entry.knowledge_question_id else "that onboarding question"
    )
    answer = (entry.value or "").strip() or "(no answer)"
    return (
        "Please open this chat. I previously answered the onboarding question "
        f'"{question}" with "{answer}". Weave a warm, natural follow-up that '
        "invites me to be more specific about that answer. Do not interrogate "
        "or list questions; keep it conversational."
    )


def format_onboarding_followup_block(session) -> str:
    """XML block for the general-chat system prompt, or empty."""
    if not is_onboarding_followup_session(session):
        return ""
    from .models import KnowledgeEntry

    pending = KnowledgeEntry.pending_followups_for(session.consumer)
    if not pending:
        return ""
    entry = next((row for row in pending if row.followup_attempts >= 1), pending[0])
    question = escape(entry.followup_prompt or "")
    answer = escape(entry.value or "")
    label = escape(entry.field.label if entry.field_id else "")
    attempt = entry.followup_attempts or 1
    return f"""
        <ONBOARDING_FOLLOW_UP>
            <!-- First general chat only. Re-ask one vague onboarding answer. -->
            <FIELD>{label}</FIELD>
            <QUESTION>{question}</QUESTION>
            <PRIOR_ANSWER>{answer}</PRIOR_ANSWER>
            <ATTEMPT>{attempt}</ATTEMPT>
            <RULES>
                - Attempt 1: weave a warm, natural follow-up that invites more
                  specificity. Do not interrogate or stack other questions.
                - Attempt 2: the server may send a more direct re-ask. If you speak,
                  stay on this topic only.
                - Do not ask about other onboarding answers until this one is done.
                - After this topic is resolved, continue a normal supportive chat.
            </RULES>
        </ONBOARDING_FOLLOW_UP>
    """


def maybe_start_onboarding_followup(session):
    """
    Latch the one-shot window on a newly created general session.

    Sets onboarding_followup_consumed_at even when nothing is flagged, then
    greets only if pending follow-ups exist.
    """
    if getattr(session, "exercise_id", None):
        return None
    consumer = session.consumer
    if not consumer.onboarded:
        return None
    if consumer.onboarding_followup_consumed_at:
        return None

    consumer.onboarding_followup_consumed_at = timezone.now()
    consumer.save(update_fields=["onboarding_followup_consumed_at", "updated_at"])

    from .models import KnowledgeEntry

    if not KnowledgeEntry.pending_followups_for(consumer):
        return None

    from ..utils.AIWorkerClient import request_session_greeting

    return request_session_greeting(session)


def handle_onboarding_followup_reply(session, user_message) -> FollowupReply:
    """
    Classify a user reply against the active follow-up.

    Returns canned_text for the direct second ask; otherwise mutates state and
    returns canned_text=None so the normal agent path continues.
    """
    if not is_onboarding_followup_session(session):
        return FollowupReply()
    if not getattr(user_message, "id", None):
        return FollowupReply()

    from .models import KnowledgeEntry

    pending = KnowledgeEntry.pending_followups_for(session.consumer)
    active = next((row for row in pending if row.followup_attempts >= 1), None)
    if active is None:
        return FollowupReply()

    user_text = (getattr(user_message, "text", None) or "").strip()
    question = active.followup_prompt or (
        active.knowledge_question.prompt if active.knowledge_question_id else ""
    )
    vague = is_answer_vague(question, user_text)

    if not vague:
        _write_improved_answer(active, value=user_text, session=session)
        activate_next_followup(session.consumer, session)
        return FollowupReply()

    if active.followup_attempts < Constants.KNOWLEDGE_FOLLOWUP_MAX_ATTEMPTS:
        _save_followup_state(active, followup_attempts=Constants.KNOWLEDGE_FOLLOWUP_MAX_ATTEMPTS)
        _invalidate_session_prompt(session)
        return FollowupReply(canned_text=Constants.KNOWLEDGE_FOLLOWUP_DIRECT_REASK)

    _clear_followup(active, session=session)
    activate_next_followup(session.consumer, session)
    return FollowupReply()
