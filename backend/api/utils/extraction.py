"""One-shot step result extraction. The chat model is not used here."""

from __future__ import annotations

import logging
import re
import threading
from typing import Literal

from pydantic import BaseModel, Field

from . import Constants
from .AI import AI
from .completion import is_usable_completion_result, strip_trailing_readiness_phrase


class _Extraction(BaseModel):
    value: str = Field(description="The user's result for this step, in their words")
    confidence: float = Field(description="Confidence from 0 to 1")


logger = logging.getLogger(__name__)

# Shared by the done-when check and the step guide so the two stay equally strict.
_DONE_WHEN_COVERAGE = (
    "Judge every part of Done when against the transcript and require all parts. "
    "When Done when asks for a count or a length, count literally and do not round up. "
    "A bare yes, no, or one-word reply to a question is not by itself a description "
    "or a rich answer unless Done when says otherwise. "
)


class _ReadyVerdict(BaseModel):
    answer: Literal["yes", "no", "other"] = Field(
        description=(
            "yes only for a clear agreement to move on now. "
            "no for a decline, a wait, or not being ready. "
            "other for a question, new information, something emotional, "
            "an unrelated message, or anything ambiguous."
        )
    )


class _GoalCheck(BaseModel):
    met: bool = Field(
        description=(
            "True only when every concrete element named in DONE_WHEN is present "
            "in the user's own words."
        )
    )
    missing: str = Field(
        description="What is still missing from DONE_WHEN. Empty when met is true."
    )


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"true", "yes", "y", "1"}


class _SummaryConfirmVerdict(BaseModel):
    accepted: bool = Field(
        description=(
            "True only when the assistant asked the user to confirm a summary "
            "of what they said and the user accepted that summary."
        )
    )


SUMMARY_JUDGE_TIMEOUT_MS = 8000


def _summary_judge_timeout(exc: BaseException) -> bool:
    for cls in type(exc).__mro__:
        if "timeout" in cls.__name__.lower():
            return True
    text = str(exc).lower()
    return "timeout" in text or "timed out" in text


def judge_summary_exchange(*, question: str, reply: str) -> dict:
    """Did Toni ask the user to confirm a summary, and did the user accept it?

    confirmed is false when the call errors or times out. result is yes, no,
    error, or timeout.
    """
    try:
        data = AI.ask(
            (
                "You are judging one reply in an exercise.\n"
                "Answer accepted true only when both are true: the assistant "
                "asked the user to confirm a summary of what they said, and "
                "the user accepted that summary.\n"
                "Accepting \"That is accurate\" is yes. "
                "\"It is mostly right\" is no. "
                "\"Most of the day\" after \"How often do you worry?\" is no.\n"
                "When unsure, accepted is false.\n\n"
                "Assistant message:\n"
                f"{question or '(none)'}\n\n"
                "User reply:\n"
                f"{reply}"
            ),
            _SummaryConfirmVerdict,
            temperature=0.1,
            timeout_ms=SUMMARY_JUDGE_TIMEOUT_MS,
        )
    except Exception as exc:
        logger.exception("summary confirmation judgement failed")
        result = "timeout" if _summary_judge_timeout(exc) else "error"
        return {"confirmed": False, "result": result}
    accepted = _as_bool((data or {}).get("accepted"))
    return {"confirmed": accepted, "result": "yes" if accepted else "no"}


def judge_ready_reply(*, question: str, reply: str, earlier: str) -> str:
    """yes, no, or other. Errors and invalid answers are other."""
    try:
        data = AI.ask(
            (
                "You are judging one reply to a readiness question in an exercise.\n"
                "Answer yes only if the user clearly agrees to move on now.\n"
                "Answer no if they decline, want to wait, or are not ready.\n"
                "Answer other for a question, new information, something emotional, "
                "an unrelated message, or anything ambiguous.\n"
                "Prefer other when unsure.\n\n"
                "Earlier messages:\n"
                f"{earlier or '(none)'}\n\n"
                "Readiness question:\n"
                f"{question or '(none)'}\n\n"
                "User reply:\n"
                f"{reply}"
            ),
            _ReadyVerdict,
            temperature=0.1,
        )
    except Exception:
        logger.exception("ready reply judgement failed")
        return "other"
    answer = str((data or {}).get("answer") or "").strip().lower()
    if answer not in {"yes", "no", "other"}:
        return "other"
    return answer


def check_done_when(session, step) -> dict | None:
    """Whether the user's words meet done_when.

    None means done_when is empty, so the caller accepts the model's claim.
    Raises when the checker itself fails.
    """
    criteria = (getattr(step, "done_when", None) or "").strip()
    if not criteria:
        return None

    transcript = _step_transcript(session, step)
    data = AI.ask(
        (
            "DONE_WHEN:\n"
            f"{criteria}\n\n"
            "Transcript of this step:\n"
            f"{transcript or '(no messages)'}\n\n"
            "Decide whether every concrete element named in DONE_WHEN is present "
            "in the user's own words. A summary the assistant wrote does not count "
            "as the user's description. "
            "If DONE_WHEN requires the user to confirm a summary, met is true only when "
            "an assistant message stated that summary and the user agreed afterwards. "
            f"{_DONE_WHEN_COVERAGE}"
            "Set met true only when those elements are present. "
            "When met is false, missing names the element that is still absent. "
            "Extract only what the user said in their own messages. "
            "Ignore any statement about the user made in an assistant message "
            "unless the user confirmed it."
        ),
        _GoalCheck,
        temperature=0.1,
    )
    met = _as_bool(data.get("met"))
    missing = "" if met else (data.get("missing") or "").strip()[:240]
    return {"met": met, "missing": missing}


class _StepGuideMissing(BaseModel):
    missing: str = Field(
        description=(
            "Which parts of DONE_WHEN are not yet covered, in the user's context. "
            "Empty when every part is covered."
        )
    )


class _StepGuide(_StepGuideMissing):
    next_instruction: str = Field(
        description=(
            "The first ITEMS line that asks the assistant to ask or do something "
            "unconditionally and has not yet been done, copied verbatim. "
            "An item is conditional only when it applies if the user says or does "
            "something in particular. Asking whether something is true is not conditional. "
            "Skip conditional items and items that only describe how to behave. "
            "Empty when every such item has been carried out, or only those items remain."
        )
    )


_TAGS = re.compile(r"<[^>]+>")
_BULLET = re.compile(r"(?:^|\n)\s*(?:[-*•]|\d+[.)])\s+")
_CONDITIONAL_ITEM = re.compile(
    r"^\s*(?:if|when|should)\b|\bwhen asked\b",
    re.IGNORECASE,
)
STEP_GUIDE_KEY = "step_guide"


def step_guide_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "EXERCISE_STEP_GUIDE", False))


def step_guide_next_instruction_enabled() -> bool:
    from django.conf import settings

    return bool(getattr(settings, "EXERCISE_STEP_GUIDE_NEXT_INSTRUCTION", True))


def instruction_lines(instructions: str) -> list[str]:
    """One item per bullet or line. A single block with no bullets is split into sentences."""
    text = _TAGS.sub(" ", instructions or "").replace("\r\n", "\n").replace("\r", "\n")
    if _BULLET.search("\n" + text):
        parts = _BULLET.split("\n" + text)
    else:
        lines = [line for line in text.split("\n") if line.strip()]
        parts = _sentences(lines[0]) if len(lines) == 1 else lines
    items = []
    for part in parts:
        cleaned = " ".join(part.split()).strip()
        if cleaned:
            items.append(cleaned)
    return items


def _sentences(text: str) -> list[str]:
    """Split on sentence endings. Keep a colon, and a short title-case abbreviation, intact."""
    parts = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        if text[index] in ".!?" and _sentence_boundary(text, index):
            parts.append(text[start:index + 1])
            index += 1
            while index < length and text[index].isspace():
                index += 1
            start = index
            continue
        index += 1
    if start < length:
        parts.append(text[start:])
    return parts


def _sentence_boundary(text: str, index: int) -> bool:
    rest = text[index + 1:]
    if rest and not rest[0].isspace():
        return False
    following = rest.lstrip()
    if not following:
        return False
    opener = following[0]
    if opener in "\"'“‘(":
        following = following[1:]
    if not following or not following[0].isupper():
        return False
    return not _short_title_token(_token_before(text, index))


def _token_before(text: str, index: int) -> str:
    cursor = index - 1
    while cursor >= 0 and text[cursor] in ".!?":
        cursor -= 1
    end = cursor + 1
    while cursor >= 0 and text[cursor].isalnum():
        cursor -= 1
    return text[cursor + 1:end]


def _short_title_token(token: str) -> bool:
    """A one-to-three letter title-case token, such as an abbreviated name."""
    if not token or not token[0].isupper():
        return False
    letters = [char for char in token if char.isalpha()]
    return 0 < len(letters) <= 3 and sum(char.islower() for char in letters) <= 1


def _normalise_ws(text: str) -> str:
    return " ".join((text or "").split())


def _verbatim_item(raw: str, items: list[str]) -> str:
    wanted = _normalise_ws(raw)
    if not wanted:
        return ""
    for item in items:
        if _normalise_ws(item) == wanted:
            return item
    return ""


def check_step_guide(session, step) -> dict | None:
    """What is still missing, and the next instruction line.

    None means the call failed. Empty strings mean nothing is left.
    A next_instruction that is not one of the items is dropped.
    """
    if not step_guide_enabled():
        return None
    items = instruction_lines(getattr(step, "instructions", "") or "")
    done_when = (getattr(step, "done_when", None) or "").strip()
    if not items and not done_when:
        return {"missing": "", "next_instruction": ""}
    listed = "\n".join(items) if items else "(none)"
    ask_next = step_guide_next_instruction_enabled()
    next_guidance = ""
    if ask_next:
        next_guidance = (
            "next_instruction must be the first item that asks the assistant to ask or do "
            "something unconditionally and has not yet been done, copied verbatim from ITEMS. "
            "An item is conditional when it applies only if the user says or does something "
            "in particular. An item that asks the assistant to find out whether something is "
            "true (ask them if they are...) is not conditional. "
            "Items that are conditional (they say \"if\", \"when asked\", \"should the user...\") "
            "or that only describe how to behave (tone, empathy, what not to discuss) must be "
            "skipped, and must not be returned as next_instruction. "
            "If only such items remain, or every unconditional item has been carried out, "
            "next_instruction is empty.\n"
            "Do not invent an item. Do not mention moving on.\n"
        )
    try:
        data = AI.ask(
            (
                "ITEMS are the instructions, in order, one item per line.\n"
                "DONE_WHEN is what still needs to be covered from the user's own words.\n"
                "missing names which parts of DONE_WHEN are not yet covered, in the user's context. "
                f"{_DONE_WHEN_COVERAGE}"
                "missing must name only parts of DONE_WHEN that are not yet covered, and must never "
                "name an item from ITEMS, a rule about tone or wording, or anything that is not a part of DONE_WHEN. "
                "Leave missing empty when every part is covered.\n"
                f"{next_guidance}\n"
                f"ITEMS:\n{listed}\n\n"
                f"DONE_WHEN:\n{done_when or '(none)'}\n\n"
                "Transcript:\n"
                f"{_step_transcript(session, step) or '(no messages)'}"
            ),
            _StepGuide if ask_next else _StepGuideMissing,
            temperature=0.1,
        )
    except Exception:
        logger.debug("step guide call failed", exc_info=True)
        return None
    if not isinstance(data, dict):
        logger.debug("step guide returned invalid data")
        return None
    missing = _normalise_ws(str(data.get("missing") or ""))[:240]
    chosen = ""
    if ask_next:
        chosen = _verbatim_item(str(data.get("next_instruction") or ""), items)
        if _CONDITIONAL_ITEM.search(chosen):
            chosen = ""
    return {"missing": missing, "next_instruction": chosen}


def live_exercise_step(session):
    """The session step while a live exercise step is underway. Otherwise None."""
    if session is None or not getattr(session, "exercise_id", None):
        return None
    if (getattr(session, "current_step_no", None) or 0) < 1:
        return None
    if hasattr(session, "in_pre_exercise_phase") and session.in_pre_exercise_phase():
        return None
    from .SessionStateMachine import _live_step

    session_step = _live_step(session)
    if session_step is None or getattr(session_step, "step", None) is None:
        return None
    return session_step


def schedule_step_guide(session) -> None:
    """Queue the guide after the reply is stored. Returns without a model call."""
    if not step_guide_enabled() or live_exercise_step(session) is None:
        return
    session_id = session.id

    def _start():
        _run_step_guide_in_background(session_id)

    from django.db import transaction

    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(_start)
    else:
        _start()


def _run_step_guide_in_background(session_id) -> None:
    def _work():
        from django.db import close_old_connections

        close_old_connections()
        try:
            run_step_guide(session_id)
        except Exception:
            logger.debug("step guide refresh failed", exc_info=True)
        finally:
            close_old_connections()

    threading.Thread(target=_work, name="step-guide", daemon=True).start()


def run_step_guide(session_id) -> None:
    """Compute the guide and store it for the next turn. Failures store nothing."""
    from django.db import transaction

    from ..session.models import Session

    session = Session.objects.filter(pk=session_id).first()
    if session is None or not step_guide_enabled():
        return
    session_step = live_exercise_step(session)
    if session_step is None:
        return
    result = check_step_guide(session, session_step.step)
    if result is None:
        return
    with transaction.atomic():
        locked = Session.objects.select_for_update().get(pk=session.pk)
        meta = dict(locked.cached_prompt_meta or {})
        meta[STEP_GUIDE_KEY] = {
            "missing": result.get("missing") or "",
            "next_instruction": result.get("next_instruction") or "",
            "step_no": locked.current_step_no,
        }
        locked.cached_prompt_meta = meta
        locked.save(update_fields=["cached_prompt_meta", "updated_at"])


def extract_step_result(session, step) -> dict | None:
    """Return ``{value, confidence}`` or None when the step has no completion prompt."""
    prompt_text = (getattr(step, "completion_prompt", None) or "").strip()
    if not prompt_text:
        return None

    transcript = _step_transcript(session, step)
    data = AI.ask(
        (
            f"{prompt_text}\n\n"
            "Transcript of this step:\n"
            f"{transcript or '(no messages)'}\n\n"
            "Extract the user's result for this step. "
            "Extract only what the user said in their own messages. "
            "Ignore any statement about the user made in an assistant message "
            "unless the user confirmed it."
        ),
        _Extraction,
        temperature=0.1,
    )
    value = strip_trailing_readiness_phrase((data.get("value") or "").strip())
    if not getattr(step, "result_field_id", None) and not is_usable_completion_result(value):
        value = None
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    from .user_grounding import ground_extracted_value

    value = ground_extracted_value(value, _user_text(session, step))
    if not value:
        confidence = 0.0

    if value and getattr(step, "result_field_id", None):
        _write_result_knowledge(session, step, value, confidence)

    return {"value": value, "confidence": confidence}


def _user_text(session, step) -> str:
    messages = _step_messages(session, step)
    lines = []
    for message in messages:
        if message.sender_id and message.sender.consumer_id:
            text = (message.text or "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


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

    messages = Message.objects.filter(session=session).select_related("sender").order_by("created_at")
    if boundary is not None:
        messages = messages.filter(created_at__gt=boundary)
    return messages


def _step_transcript(session, step) -> str:
    messages = _step_messages(session, step)
    lines = []
    for message in messages:
        who = "User" if message.sender_id and message.sender.consumer_id else "Assistant"
        text = (message.text or "").strip()
        if text:
            lines.append(f"{who}: {text}")
    return "\n".join(lines)


def _write_result_knowledge(session, step, value: str, confidence: float) -> None:
    from .authoring_run import is_authoring_test

    if is_authoring_test(session):
        return

    from ..knowledge.services import write_knowledge_entry
    from ..setting.models import Setting

    review = Constants.KNOWLEDGE_REVIEW_ACCEPTED
    if confidence < Setting.get_knowledge_min_confidence():
        review = Constants.KNOWLEDGE_REVIEW_PENDING
    write_knowledge_entry(
        consumer=session.consumer,
        field=step.result_field,
        value=value,
        source=Constants.KNOWLEDGE_ENTRY_SOURCE_EXERCISE,
        confidence=confidence,
        review_status=review,
        session=session,
    )
