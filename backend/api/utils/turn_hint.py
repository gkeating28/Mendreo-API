"""Open-question chip shaping and the one-turn thin-answer hint."""

from __future__ import annotations

import re

from . import Constants

_TRAILING_ELLIPSIS = re.compile(r"(?:\s*(?:\.{3}|…))+\s*$")

FOLLOW_UP_HINT = (
    "The reply was brief. Stay on this step. Ask one follow-up that this step's "
    "instructions still need. One question only. Do not start another exercise or activity."
)
DEPTH_HINT = (
    "The step's result is not yet specific enough to record. "
    "Ask one follow-up that would make it concrete."
)
ACCEPT_HINT = (
    "You have already followed up twice on this question. Accept the answer and "
    "continue with the next part of this step's instructions. "
    "Do not start another exercise or activity."
)
STAY_ON_STEP_HINT = (
    "That reply offered a technique or activity this step does not instruct. "
    "Discard that offer and continue this step. "
    "If the instructions say to summarise, summarise in the user's words and ask if you have it right. "
    "If they have already confirmed the summary, ask whether they are ready for the next step. "
    "Do not start another technique."
)
ON_STEP_FALLBACK = (
    "Let's stay with this step. What else can you tell me about it?"
)
ABOUT_THE_USER_HINT = (
    "{user_name} is asking what you know about them.\n"
    "Answer in two sentences from <CLIENT_SUMMARY>, <KNOWLEDGE> and <SESSION_CONTEXT>, "
    "naming one or two specific things from them. Do not say you have no information. "
    "Then ask one simple question."
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


def _strip_trailing_ellipsis(text: str) -> str:
    stripped = _TRAILING_ELLIPSIS.sub("", text)
    if stripped == text:
        return text
    return stripped.rstrip()


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
        text = _strip_trailing_ellipsis(text)
        if not text:
            continue
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


SUMMARY_CONFIRM_HINT = (
    "This step is not done. Summarise what this step asked for, in the user's words, "
    "then ask if you have that right. Do not ask them to move on, and do not start another exercise."
)


def goal_hint_text(missing: str) -> str:
    gap = (missing or "").strip() or "what this step still requires"
    return (
        "This step is not done yet. "
        f"Ask one question that would supply what is still missing: {gap}"
    )


def about_the_user_hint(session, text: str) -> str | None:
    """General chat only. Skipped when the three client blocks are still empty."""
    if getattr(session, "exercise_id", None):
        return None
    from ..grounding.retrieval import _ABOUT_THE_USER

    if not _ABOUT_THE_USER.search(text or ""):
        return None
    if _client_blocks_are_new(session):
        return None
    consumer = session.consumer
    user_name = ""
    if consumer is not None:
        user_name = getattr(getattr(consumer, "user", None), "first_name", "") or ""
    return ABOUT_THE_USER_HINT.replace("{user_name}", user_name.strip() or "there")


def _client_blocks_are_new(session) -> bool:
    """True when summary, knowledge, and session context have nothing to name."""
    from .prompt_blocks import render_client_summary, render_knowledge, render_session_context

    consumer = session.consumer
    summary = (render_client_summary(consumer) or "").strip()
    knowledge = (render_knowledge(consumer, "general") or "").strip()
    context = render_session_context(consumer, session) or ""
    summary_new = (
        not summary or summary == "No previous conversations exist with this user."
    )
    knowledge_new = not knowledge or (
        "No structured knowledge recorded" in knowledge and "\n-" not in knowledge
    )
    context_new = (
        "Days since last session: none" in context
        and "Last exercise completed: none" in context
        and "Exercises completed in the last 7 days: none" in context
        and "Today's completed sessions: none" in context
    )
    return summary_new and knowledge_new and context_new


def user_prompt_with_hint(session, user_message) -> str:
    """User text plus a turn hint that is not stored on the message."""
    from ..message.models import Message

    text = user_message.text or ""
    about = about_the_user_hint(session, text)
    if about:
        return f"{text}\n\n<TURN_HINT>\n{about}\n</TURN_HINT>"
    goal = _consume_goal_hint(session)
    if goal:
        return f"{text}\n\n<TURN_HINT>\n{goal}\n</TURN_HINT>"
    depth = _consume_depth_hint(session)
    if depth:
        return f"{text}\n\n<TURN_HINT>\n{depth}\n</TURN_HINT>"
    previous = (
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("-created_at")
        .first()
    )
    hint = turn_hint_text(previous, text)
    if not hint:
        return text
    return f"{text}\n\n<TURN_HINT>\n{hint}\n</TURN_HINT>"


def _consume_goal_hint(session) -> str | None:
    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    if "goal_hint" not in meta:
        return None
    hint = (meta.pop("goal_hint") or "").strip()
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    return hint or None


def _consume_depth_hint(session) -> str | None:
    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    if not meta.get("depth_hint_step_id"):
        return None
    meta.pop("depth_hint_step_id", None)
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    return DEPTH_HINT


def last_agent_message(session):
    from ..message.models import Message

    return (
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("-created_at")
        .first()
    )
