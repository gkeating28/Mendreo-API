"""A step that requires a confirmed summary cannot finish before the user agrees."""

from __future__ import annotations

import logging
import re

from django.conf import settings

from . import Constants

logger = logging.getLogger(__name__)

_REQUIRED = re.compile(
    r"(?:confirm(?:ed|s|ing)?|agree(?:d|s)?)\s+(?:with\s+)?(?:that\s+)?(?:the\s+)?summary"
    r"|summary\s+is\s+accurate",
    re.IGNORECASE,
)

_ASK = re.compile(
    r"\b(?:did i (?:get|capture|understand)|have i got|have i understood that right|"
    r"do i have (?:that|this) right|"
    r"does that (?:sound|seem|feel) right|does this (?:plan |summary )?sound right|"
    r"does this summary accurately reflect|"
    r"is that (?:right|accurate|correct)|is this right|"
    r"did i (?:get|have) (?:that|it) right|does that cover it)\b",
    re.IGNORECASE,
)

_SUMMARY_AFFIRM_START = re.compile(
    r"^(?:yes|yeah|yep|correct|right|exactly|that's right|that's correct|"
    r"that covers it|sounds good|looks good|perfect)\b",
    re.IGNORECASE,
)
_SUMMARY_AFFIRM_BLOCK = re.compile(
    r"\b(?:no|not|but|except|change|wrong)\b",
    re.IGNORECASE,
)


def summary_confirmation_required(done_when: str) -> bool:
    return bool(_REQUIRED.search(done_when or ""))


def summary_confirmation_rule(done_when: str) -> str:
    if not summary_confirmation_required(done_when):
        return ""
    return (
        "\n\nBefore this step can finish, one message must summarise what this step "
        "asked for, in the user's words, and ask if that summary is right. "
        "Do not set step_goal_met on that message. "
        "Do not ask if they are ready for the next step until they have confirmed the summary."
    )


def _final_sentence(text: str) -> str:
    raw = " ".join((text or "").split())
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", raw) if part.strip()]
    return parts[-1] if parts else ""


def is_summary_confirmation(text: str) -> bool:
    """A recap that names what was said and asks if it is right.

    A short question, or a readiness question, does not count.
    The ask has to be in the final sentence.
    """
    raw = " ".join((text or "").split())
    if len(raw.split()) < 12:
        return False
    return bool(_ASK.search(_final_sentence(raw)))


def _affirm_text(text: str) -> str:
    return " ".join(
        (text or "").strip().lower().replace("\u2019", "'").replace("\u2018", "'").split()
    ).rstrip(".!")


def matches_summary_affirmation(text: str) -> bool:
    """The fixed agreement words. Editing ready phrases does not change this."""
    return _affirm_text(text) in Constants.SUMMARY_AFFIRMATIONS


def is_summary_affirmation(text: str) -> bool:
    """A short agreement after a summary."""
    if matches_summary_affirmation(text):
        return True
    raw = _affirm_text(text)
    words = raw.split()
    if not words or len(words) > 10:
        return False
    if _SUMMARY_AFFIRM_BLOCK.search(raw):
        return False
    return bool(_SUMMARY_AFFIRM_START.match(raw))


def summary_reply_declines(text: str) -> bool:
    """The existing block: a reply that says no, not, but, except, change, or wrong."""
    return bool(_SUMMARY_AFFIRM_BLOCK.search(_affirm_text(text)))


SUMMARY_CONFIRM_EXPECT_STEP = "summary_confirm_expect_step"
SUMMARY_CONFIRM_MESSAGE_ID = "summary_confirm_message_id"
SUMMARY_CONFIRM_STEP_NO = "summary_confirm_step_no"
SUMMARY_CONFIRM_VERDICTS = "summary_confirm_verdicts"


def summary_confirm_judge_enabled() -> bool:
    return bool(getattr(settings, "EXERCISE_SUMMARY_CONFIRM_JUDGE", False))


def _verdict_cache(session) -> dict:
    raw = (session.cached_prompt_meta or {}).get(SUMMARY_CONFIRM_VERDICTS)
    return dict(raw) if isinstance(raw, dict) else {}


def _remember_verdict(session, user_message, verdict: dict) -> None:
    message_id = getattr(user_message, "id", None)
    if not message_id:
        return
    try:
        meta = dict(session.cached_prompt_meta or {})
        cache = dict(meta.get(SUMMARY_CONFIRM_VERDICTS) or {})
        cache[str(message_id)] = {
            "confirmed": bool(verdict.get("confirmed")),
            "result": verdict.get("result") or "error",
        }
        meta[SUMMARY_CONFIRM_VERDICTS] = cache
        session.cached_prompt_meta = meta
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
    except Exception:
        logger.exception(
            "summary verdict cache failed for session=%s",
            getattr(session, "id", None),
        )


def _stamp_summary_verdict(agent_message, verdict: dict) -> None:
    """Put the judge result on the assistant message, next to check_done_when."""
    if agent_message is None or not getattr(agent_message, "pk", None):
        return
    try:
        usage = dict(agent_message.usage) if isinstance(agent_message.usage, dict) else {}
        decision = dict(usage.get("step_decision") or {})
        recorded = {
            "confirmed": bool(verdict.get("confirmed")),
            "result": verdict.get("result") or "error",
        }
        decision["summary_confirm"] = recorded
        usage["step_decision"] = decision
        agent_message.usage = usage
        agent_message.save(update_fields=["usage", "updated_at"])

        from ..message.models import TurnPrompt

        prompt = TurnPrompt.objects.filter(message=agent_message).first()
        if prompt is None:
            return
        rows = []
        updated = False
        for row in list(prompt.decisions or []):
            if isinstance(row, dict) and row.get("type") == "step_hold":
                row = dict(row)
                inputs = dict(row.get("inputs") or {})
                inputs["summary_confirm"] = recorded
                row["inputs"] = inputs
                updated = True
            rows.append(row)
        if updated:
            prompt.decisions = rows
            prompt.save(update_fields=["decisions", "updated_at"])
    except Exception:
        logger.exception(
            "summary verdict note failed for message=%s",
            getattr(agent_message, "id", None),
        )


def summary_exchange_verdict(session, question_message, user_message) -> dict:
    """Judge this pair once. Later reads use the cached verdict for that reply."""
    cached = _verdict_cache(session).get(str(getattr(user_message, "id", "") or ""))
    if isinstance(cached, dict) and cached.get("result"):
        return cached
    from .extraction import judge_summary_exchange

    verdict = judge_summary_exchange(
        question=(getattr(question_message, "text", None) or ""),
        reply=(getattr(user_message, "text", None) or ""),
    )
    _remember_verdict(session, user_message, verdict)
    _stamp_summary_verdict(question_message, verdict)
    return verdict


def note_held_summary(session, meta: dict, agent_message, *, met: bool) -> None:
    """Mark this question when the hold is a summary. Otherwise wait for the next one."""
    text = (getattr(agent_message, "text", None) or "").strip()
    step_no = session.current_step_no or 1
    if met and getattr(agent_message, "id", None) and text.endswith("?"):
        meta[SUMMARY_CONFIRM_MESSAGE_ID] = str(agent_message.id)
        meta[SUMMARY_CONFIRM_STEP_NO] = step_no
        meta.pop(SUMMARY_CONFIRM_EXPECT_STEP, None)
        return
    meta[SUMMARY_CONFIRM_EXPECT_STEP] = step_no


def mark_expected_summary_question(session, agent_message) -> None:
    """If the reply expected after a non-question hold ends with ?, remember its id."""
    meta = dict(session.cached_prompt_meta or {})
    if SUMMARY_CONFIRM_EXPECT_STEP not in meta:
        return
    expected = meta.pop(SUMMARY_CONFIRM_EXPECT_STEP, None)
    step_no = session.current_step_no or 1
    try:
        expected_no = int(expected)
    except (TypeError, ValueError):
        expected_no = None
    text = (getattr(agent_message, "text", None) or "").strip()
    if (
        expected_no == step_no
        and getattr(agent_message, "id", None)
        and text.endswith("?")
    ):
        meta[SUMMARY_CONFIRM_MESSAGE_ID] = str(agent_message.id)
        meta[SUMMARY_CONFIRM_STEP_NO] = step_no
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])


def is_recorded_summary_confirmation(session, message) -> bool:
    if message is None or not getattr(message, "id", None):
        return False
    meta = session.cached_prompt_meta or {}
    if str(meta.get(SUMMARY_CONFIRM_MESSAGE_ID) or "") != str(message.id):
        return False
    try:
        marked_step = int(meta.get(SUMMARY_CONFIRM_STEP_NO) or 0)
    except (TypeError, ValueError):
        return False
    return marked_step == (session.current_step_no or 1)


def structural_summary_reply_confirms(text: str) -> bool:
    """A typed reply or a tapped chip. Both have to be a short agreement.

    The decline words (no, not, but, except, change, wrong) still refuse it.
    """
    if summary_reply_declines(text):
        return False
    return is_summary_affirmation(text)


_JUDGE_PAIR_CAP = 2


def _summary_judge_pairs(messages, agreed) -> list:
    """Question and reply pairs the judge would see, oldest first.

    A reply the phrase check already accepts is not a pair.
    """
    pairs = []
    pending = False
    question = None
    for message in messages:
        text = message.text or ""
        is_user = bool(getattr(message.sender, "consumer_id", None))
        if not is_user and is_summary_confirmation(text):
            pending = True
            question = message
            continue
        if not is_user and text.strip().endswith("?"):
            pending = False
            question = message
            continue
        if not is_user:
            continue
        if pending and agreed(text):
            pending = False
            question = None
            continue
        if question is not None and (question.text or "").strip().endswith("?"):
            pairs.append((question, message))
        pending = False
        question = None
    return pairs


def _judged_reply_ids(session, pairs) -> set:
    """Reply ids the judge may read this run.

    Cached verdicts are included and do not use up the two fresh calls.
    Older uncached pairs are left out, so they count as not confirmed.
    """
    allowed = set()
    fresh = 0
    for _question, user in reversed(pairs):
        message_id = str(getattr(user, "id", "") or "")
        cached = _verdict_cache(session).get(message_id)
        if isinstance(cached, dict) and cached.get("result"):
            allowed.add(message_id)
            continue
        if fresh >= _JUDGE_PAIR_CAP:
            continue
        allowed.add(message_id)
        fresh += 1
    return allowed


def summary_was_confirmed(session, step) -> bool:
    """True when the user agreed after an assistant summary in this step."""
    from .SessionStateMachine import _is_last_step

    agreed = is_summary_affirmation if _is_last_step(session) else matches_summary_affirmation
    judge = summary_confirm_judge_enabled() and summary_confirmation_required(
        getattr(step, "done_when", None) or ""
    )
    messages = list(_step_messages(session, step))
    allowed = _judged_reply_ids(session, _summary_judge_pairs(messages, agreed)) if judge else set()
    pending = False
    question = None
    for message in messages:
        text = message.text or ""
        is_user = bool(getattr(message.sender, "consumer_id", None))
        if not is_user and is_summary_confirmation(text):
            pending = True
            question = message
            continue
        if not is_user and judge and text.strip().endswith("?"):
            pending = False
            question = message
            continue
        if is_user and pending and agreed(text):
            return True
        if (
            is_user
            and judge
            and question is not None
            and (question.text or "").strip().endswith("?")
            and str(getattr(message, "id", "") or "") in allowed
        ):
            if summary_exchange_verdict(session, question, message).get("confirmed"):
                return True
        if is_user:
            pending = False
            question = None
    return False


def _step_messages(session, step):
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

    messages = (
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("created_at")
    )
    if boundary is not None:
        messages = messages.filter(created_at__gt=boundary)
    return messages
