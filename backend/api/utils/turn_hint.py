"""Open-question chip shaping and the one-turn thin-answer hint."""

from __future__ import annotations

from . import Constants

FOLLOW_UP_HINT = (
    "The reply was brief. Ask one specific follow-up about when, where or what "
    "happened before moving on. One question only."
)
ACCEPT_HINT = (
    "You have already followed up twice on this question. Accept the answer and continue."
)


def normalize_question_kind(value) -> str:
    text = (value or "").strip().lower()
    if text in Constants.QUESTION_KINDS:
        return text
    return Constants.QUESTION_KIND_NONE


def answer_is_thin(value: str, generic_answers) -> bool:
    """True when an answer is empty, generic, or under the thin-word minimum."""
    from ..setting.models import Setting

    cleaned = (value or "").strip()
    if not cleaned:
        return True
    if is_generic_answer(cleaned, generic_answers):
        return True
    return len(cleaned.split()) < Setting.get_thin_answer_min_words()


def is_thin_answer(text: str) -> bool:
    """Thin reply in chat, judged against the default generic-answer list."""
    from ..setting.models import Setting

    return answer_is_thin(text, Setting.get_generic_answers_default())


def is_generic_answer(value: str, generic_answers) -> bool:
    cleaned = (value or "").strip().casefold()
    if not cleaned:
        return False
    for item in generic_answers or []:
        if cleaned == str(item or "").strip().casefold():
            return True
    return False


def generic_answers_for(question) -> list:
    """Question list when it has one, otherwise the setting default."""
    from ..setting.models import Setting

    own = list(getattr(question, "generic_answers", None) or [])
    if own:
        return own
    return Setting.get_generic_answers_default()


def entry_quality(value: str, *, response_type: str, generic_answers) -> tuple[float, str]:
    """Confidence and review status for an onboarding answer."""
    text_types = {
        Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
        Constants.QUESTION_TYPE_TEXT,
    }
    if response_type in text_types and answer_is_thin(value, generic_answers):
        return Constants.THIN_ANSWER_CONFIDENCE, Constants.KNOWLEDGE_REVIEW_PENDING
    return 1.0, Constants.KNOWLEDGE_REVIEW_ACCEPTED


def shape_chips(chips, question_kind: str):
    """Open questions keep at most two sentence-starter chips."""
    if normalize_question_kind(question_kind) != Constants.QUESTION_KIND_OPEN:
        return chips
    if not chips:
        return chips

    from ..setting.models import Setting

    generic = Setting.get_generic_answers_default()
    kept = []
    for raw in chips:
        text = (raw or "").strip()
        if not text:
            continue
        if is_generic_answer(text, generic) or len(text.split()) == 1:
            continue
        if not text.endswith("...") and not text.endswith("…"):
            text = text + "..."
        kept.append(text)
        if len(kept) == 2:
            break
    return kept


def turn_hint_text(previous, user_text: str) -> str | None:
    """Hint for this model call only. None unless the previous question was open."""
    if previous is None:
        return None
    kind = normalize_question_kind(getattr(previous, "question_kind", None))
    if kind != Constants.QUESTION_KIND_OPEN:
        return None
    if not is_thin_answer(user_text):
        return None
    if (getattr(previous, "probe_count", 0) or 0) >= 2:
        return ACCEPT_HINT
    return FOLLOW_UP_HINT


def probe_count_for(previous, question_kind: str) -> int:
    kind = normalize_question_kind(question_kind)
    previous_kind = normalize_question_kind(
        getattr(previous, "question_kind", None) if previous is not None else None
    )
    if kind == Constants.QUESTION_KIND_OPEN and previous_kind == Constants.QUESTION_KIND_OPEN:
        return (getattr(previous, "probe_count", 0) or 0) + 1
    return 0


def user_prompt_with_hint(session, user_message) -> str:
    """User text plus a turn hint that is not stored on the message."""
    from ..message.models import Message

    text = user_message.text or ""
    previous = (
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("-created_at")
        .first()
    )
    hint = turn_hint_text(previous, text)
    if not hint:
        return text
    return f"{text}\n\n<TURN_HINT>\n{hint}\n</TURN_HINT>"


def last_agent_message(session):
    from ..message.models import Message

    return (
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("-created_at")
        .first()
    )
