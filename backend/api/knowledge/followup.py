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
    suggested_responses: list[str] | None = None
    reasoning: str | None = None
    decline_after_agent: bool = False


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

_THIN_OPENERS = frozenset(
    {
        "hello",
        "hi",
        "hey",
        "yo",
        "hiya",
        "howdy",
        "sup",
        "hey there",
        "hi there",
        "hello there",
        "hey toni",
        "hi toni",
        "hello toni",
        "good morning",
        "good afternoon",
        "good evening",
        "whats up",
        "what s up",
        "how are you",
        "hows it going",
        "how is it going",
    }
)


def _normalize_chip(answer: str) -> str:
    cleaned = (answer or "").strip().lower().replace("'", "")
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def _normalize_answer(answer: str) -> str:
    return _normalize_chip(answer)


_GRANT_ALIASES = frozenset(
    {
        _normalize_chip(Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_YES),
        "yes",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
    }
)

_DECLINE_ALIASES = frozenset(
    {
        _normalize_chip(Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_NO),
        "no",
        "nope",
        "nah",
        "not now",
        "no thanks",
        "maybe later",
    }
)


def looks_vague(answer: str) -> bool:
    """True for short generic non-answers. Fail-open (False) when unsure."""
    normalized = _normalize_answer(answer)
    return bool(normalized) and normalized in _VAGUE_ANSWER_PHRASES


def looks_thin_opener(answer: str) -> bool:
    """True for greetings and platitudes that are not a real first-turn topic."""
    normalized = _normalize_answer(answer)
    if not normalized:
        return True
    if normalized in _THIN_OPENERS:
        return True
    return looks_vague(answer)


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
    """True for the general session that claimed the one-shot follow-up window."""
    if getattr(session, "exercise_id", None):
        return False
    consumer = getattr(session, "consumer", None)
    if consumer is None:
        return False
    claimed_id = getattr(consumer, "onboarding_followup_session_id", None)
    if claimed_id:
        return session.id == claimed_id
    return bool(getattr(consumer, "onboarded", False)) and not getattr(
        consumer, "onboarding_followup_consumed_at", None
    )


def should_inject_onboarding_followup(session) -> bool:
    if not is_onboarding_followup_session(session):
        return False
    consumer = session.consumer
    if getattr(consumer, "onboarding_followup_consent", None) == (
        Constants.ONBOARDING_FOLLOWUP_CONSENT_DECLINED
    ):
        return False
    from .models import KnowledgeEntry

    return bool(KnowledgeEntry.pending_followups_for(consumer))


def _invalidate_session_prompt(session) -> None:
    if session is None:
        return
    if not getattr(session, "cached_prompt", None):
        return
    session.cached_prompt = None
    session.save(update_fields=["cached_prompt", "updated_at"])


def _save_consumer(consumer, **fields) -> None:
    for key, value in fields.items():
        setattr(consumer, key, value)
    update_fields = list(fields.keys()) + ["updated_at"]
    consumer.save(update_fields=update_fields)


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


def _pending_entry(consumer):
    from .models import KnowledgeEntry

    pending = KnowledgeEntry.pending_followups_for(consumer)
    if not pending:
        return None
    return next((row for row in pending if row.followup_attempts >= 1), pending[0])


def _permission_ask_text(entry) -> str:
    question = (entry.followup_prompt or "").strip() or "that"
    answer = (entry.value or "").strip() or "that"
    return (
        f'You answered "{question}" with "{answer}". '
        "We can go into that now, or leave it."
    )


def _claim_followup_session(consumer, session) -> None:
    if getattr(consumer, "onboarding_followup_consumed_at", None):
        return
    _save_consumer(
        consumer,
        onboarding_followup_consumed_at=timezone.now(),
        onboarding_followup_session_id=session.id,
    )


def decline_onboarding_followup(session) -> None:
    """Close the one-shot window after a real-topic opener or an explicit no."""
    consumer = getattr(session, "consumer", None)
    if consumer is None:
        return
    _save_consumer(
        consumer,
        onboarding_followup_consent=Constants.ONBOARDING_FOLLOWUP_CONSENT_DECLINED,
    )
    _invalidate_session_prompt(session)
    from .services import invalidate_consumer_prompt_cache

    invalidate_consumer_prompt_cache(consumer)


def greeting_user_prompt_for_session(session) -> str | None:
    """Unused for general chat. Exercise openers do not call this."""
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


def _followup_phase(consumer, entry) -> str:
    consent = getattr(consumer, "onboarding_followup_consent", None)
    if consent == Constants.ONBOARDING_FOLLOWUP_CONSENT_PENDING:
        return "permission"
    if consent == Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED or (
        entry and (entry.followup_attempts or 0) >= 1
    ):
        return "followup"
    return "stay_on_opener"


def format_onboarding_followup_block(session) -> str:
    """XML block for the general-chat system prompt, or empty."""
    if not should_inject_onboarding_followup(session):
        return ""
    entry = _pending_entry(session.consumer)
    if entry is None:
        return ""
    question = escape(entry.followup_prompt or "")
    answer = escape(entry.value or "")
    label = escape(entry.field.label if entry.field_id else "")
    phase = _followup_phase(session.consumer, entry)
    attempt = entry.followup_attempts or 0
    return f"""
        <ONBOARDING_FOLLOW_UP>
            <!-- Outranks Daily Check-in and Triage until this block is gone. -->
            <FIELD>{label}</FIELD>
            <QUESTION>{question}</QUESTION>
            <PRIOR_ANSWER>{answer}</PRIOR_ANSWER>
            <PHASE>{phase}</PHASE>
            <ATTEMPT>{attempt}</ATTEMPT>
            <RULES>
                - While this block is present: do not run a daily check-in,
                  do not call get_exercise, do not offer an exercise.
                - One question only. Two sentences max.

                PHASE stay_on_opener (first message is already a real topic):
                - Reply only to what they just said.
                - Do not mention PRIOR_ANSWER, do not ask permission,
                  do not re-ask the onboarding question.

                PHASE permission (server may send this as a canned line):
                - If you speak: one permission ask about PRIOR_ANSWER only.
                - Do not also check in or triage.

                PHASE followup (they agreed, or they started answering it):
                - Attempt 1: weave a warm follow-up that invites more
                  specificity about PRIOR_ANSWER. Do not stack questions.
                - Attempt 2: if you speak, stay on this topic only.
                  The server may send a direct re-ask.
                - After this topic is resolved, continue a normal
                  supportive chat (this block will be removed).
            </RULES>
        </ONBOARDING_FOLLOW_UP>
    """


def maybe_start_onboarding_followup(session):
    """
    Session create no longer claims the follow-up window or greets.

    The one-shot latch is consumed on the first general-chat user message.
    Kept as a no-op so session create sites do not need a special case.
    """
    del session
    return None


def _permission_reply_for(entry) -> FollowupReply:
    return FollowupReply(
        canned_text=_permission_ask_text(entry),
        suggested_responses=list(Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_CHIPS),
        reasoning="onboarding_followup_permission",
    )


def _decline_ack() -> FollowupReply:
    return FollowupReply(
        canned_text=Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_DECLINE_ACK,
        suggested_responses=[],
        reasoning="onboarding_followup_declined",
    )


def _is_grant_text(text: str) -> bool:
    return _normalize_answer(text) in _GRANT_ALIASES


def _is_decline_text(text: str) -> bool:
    return _normalize_answer(text) in _DECLINE_ALIASES


def _handle_first_user_message(session, consumer, user_text: str, pending) -> FollowupReply:
    _claim_followup_session(consumer, session)
    if not pending:
        return FollowupReply()

    entry = pending[0]
    if looks_thin_opener(user_text):
        _save_consumer(
            consumer,
            onboarding_followup_consent=Constants.ONBOARDING_FOLLOWUP_CONSENT_PENDING,
        )
        return _permission_reply_for(entry)

    # Real topic: keep the block for this Gemini turn, then drop it.
    return FollowupReply(decline_after_agent=True)


def _handle_permission_reply(session, consumer, user_message, user_text: str) -> FollowupReply:
    from .models import KnowledgeEntry

    if _is_grant_text(user_text):
        _save_consumer(
            consumer,
            onboarding_followup_consent=Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED,
        )
        activate_next_followup(consumer, session)
        return FollowupReply()

    if _is_decline_text(user_text) or looks_thin_opener(user_text):
        decline_onboarding_followup(session)
        return _decline_ack()

    # Typed a real answer to the flagged question — skip chips, treat as granted.
    _save_consumer(
        consumer,
        onboarding_followup_consent=Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED,
    )
    activate_next_followup(consumer, session)
    return _classify_followup_answer(
        session, user_message, KnowledgeEntry.pending_followups_for(consumer)
    )


def _classify_followup_answer(session, user_message, pending) -> FollowupReply:
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
        return FollowupReply(
            canned_text=Constants.KNOWLEDGE_FOLLOWUP_DIRECT_REASK,
            suggested_responses=[],
            reasoning="onboarding_followup_direct_reask",
        )

    _clear_followup(active, session=session)
    activate_next_followup(session.consumer, session)
    return FollowupReply()


def handle_onboarding_followup_reply(session, user_message) -> FollowupReply:
    """
    First user message claims the one-shot window. Thin openers get a canned
    permission ask; real topics skip it. The opener is never classified as the
    follow-up answer unless they already granted permission.
    """
    if getattr(session, "exercise_id", None):
        return FollowupReply()
    if not getattr(user_message, "id", None):
        return FollowupReply()

    consumer = getattr(session, "consumer", None)
    if consumer is None or not getattr(consumer, "onboarded", False):
        return FollowupReply()

    from .models import KnowledgeEntry

    pending = KnowledgeEntry.pending_followups_for(consumer)
    user_text = (getattr(user_message, "text", None) or "").strip()
    consent = getattr(consumer, "onboarding_followup_consent", None)

    if not getattr(consumer, "onboarding_followup_consumed_at", None):
        return _handle_first_user_message(session, consumer, user_text, pending)

    if getattr(consumer, "onboarding_followup_session_id", None) != session.id:
        return FollowupReply()

    if consent == Constants.ONBOARDING_FOLLOWUP_CONSENT_DECLINED:
        return FollowupReply()

    if consent == Constants.ONBOARDING_FOLLOWUP_CONSENT_PENDING:
        if not pending:
            decline_onboarding_followup(session)
            return FollowupReply()
        return _handle_permission_reply(session, consumer, user_message, user_text)

    if consent == Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED:
        if not pending:
            return FollowupReply()
        return _classify_followup_answer(session, user_message, pending)

    return FollowupReply()
