"""Open-question chip shaping and the one-turn thin-answer hint."""

from __future__ import annotations

import logging
import re

from . import Constants

logger = logging.getLogger(__name__)

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
    "That reply did not follow this step's instructions. "
    "Do the next part of those instructions and nothing else. "
    "Do not add any technique or activity they do not name."
)
NOT_THE_LAST_STEP_HINT = (
    "This is not the last step. Do not talk about finishing, wrapping up or ending the exercise. "
    "If this step's work is done, ask only whether they are ready for the next step. "
    "Otherwise ask this step's next question."
)
LAST_STEP_HINT = (
    "This is the last step. Do not talk about moving on or a next step. "
    "If {name} has not yet confirmed your summary, summarise their decisions "
    "and their alternative action in their own words, and make the last sentence exactly "
    "\"Do I have that right?\". Do not rephrase it. "
    "If they have confirmed it, ask only whether they are ready to finish the exercise."
)
ON_STEP_FALLBACK = (
    "Let's stay with this step. What else can you tell me about it?"
)
NOT_READY_HINT = (
    "The person has just said they are not ready to move on. "
    "Reply in one or two warm sentences. "
    "Do not move to the next step, do not ask whether they are ready again, "
    "and do not start a new technique. "
    "Invite them to say more about this step or tell you when they are ready."
)
ABOUT_THE_USER_HINT = (
    "{user_name} is asking what you know about them. "
    "Everything you know is written between the <ABOUT_CLIENT> tags below, "
    "plus anything {user_name} has told you earlier in this chat. Use only that. "
    "Do not guess or add anything else, such as age, hobbies, routines or feelings "
    "that are not written there. Answer in two sentences, naming one or two specific "
    "things from it. Do not say you have no information. Then ask one simple question. "
    "Answer in the same voice and style as the rest of this chat."
)
EXERCISE_NUDGE_HINT = (
    "If a suitable exercise fits what the person has shared, offer one now: "
    "call get_exercise first, then offer it in your own words and ask if they "
    "would like to try it. If nothing fits yet, carry on and end with a gentle "
    "question. Use the same voice you have been using in this chat, including "
    "any style the person has asked for."
)
_EXERCISE_NUDGE_LIMIT = 2
_EXERCISE_NUDGE_GAP = 3
_NUDGES_SENT_KEY = "exercise_nudges_sent"
_NUDGE_LAST_AT_KEY = "exercise_nudge_last_at"


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


def thin_answer_catalogue_text() -> str:
    """Built-in rules text. The switch is live; a database error shows the default on."""
    try:
        from ..setting.models import Setting

        enabled = Setting.get_thin_answer_hint_enabled()
    except Exception:
        enabled = True
    state = "On" if enabled else "Off"
    return (
        "Thin-answer hint. turn_hint_text adds a hint for this model call only, "
        "and only after an open question when the reply is thin.\n"
        f"Thin-answer hint: {state}. Editable in Settings (thin_answer_hint_enabled).\n"
        f"Follow-up hint: {FOLLOW_UP_HINT}\n"
        f"Accept hint, after two follow-ups: {ACCEPT_HINT}"
    )


def turn_hint_text(previous, user_text: str, session=None) -> str | None:
    """Hint for this model call only. None unless the previous question was open.

    General chat has no live step, so the thin-answer hints stay off there.
    ``thin_answer_hint_enabled`` still defaults to on for exercise sessions.
    """
    if session is not None and not getattr(session, "exercise_id", None):
        return None
    from ..setting.models import Setting

    if not Setting.get_thin_answer_hint_enabled():
        return None
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
    "then make the last sentence exactly \"Do I have that right?\". Do not rephrase it. "
    "Do not ask them to move on, and do not start another exercise."
)
STEP_SUMMARY_HINT = (
    "This step has had enough questions. In this same message, write a short summary "
    "in the user's own words of the worry, the situation it happens in, and how it affects them, "
    "and make the last sentence exactly \"Do I have that right?\". Do not rephrase it. "
    "Never ask if you have that right without the summary in the message. "
    "Ask no other question."
)
STEP_READY_HINT = (
    "The user confirmed your summary. This step is done. "
    "Ask no more questions about this step. "
    "Reply with one short acknowledging sentence and then ask only whether they are ready "
    "for the next step. Set step_goal_met and asks_readiness."
)
STEP_MISSING_HINT = (
    "Before summarising, ask exactly one question to find out {missing}. "
    "That question must be specific and build on what the user has already said, "
    "and must not ask them to describe or explain everything again. "
    "Ask nothing else, and do not summarise yet."
)
STEP_ANSWER_CAP = 6
STEP_HARD_CAP = 8


def goal_hint_text(missing: str) -> str:
    gap = (missing or "").strip() or "what this step still requires"
    return (
        "This step is not done yet. "
        f"Ask one question that would supply what is still missing: {gap}"
    )


def _stored_step_no(message):
    """Message.step_no when this row has one. Unsaved rows carry a database default."""
    from django.db.models.expressions import DatabaseDefault

    if message is None:
        return None
    raw = message.__dict__.get("step_no", None)
    if raw is None or isinstance(raw, DatabaseDefault):
        return None
    return raw


def _exercise_run_started_at(session):
    """When this exercise run's steps began.

    A finished check-in stamps pre_exercise_completed_at. That is the start of
    the steps. A run with no check-in starts when the session row was created.
    """
    return getattr(session, "pre_exercise_completed_at", None) or getattr(
        session, "created_at", None
    )


def _null_step_lower_bound(session):
    """Earliest time a user message with no step_no can belong to the live step.

    Check-in messages are at or before pre_exercise_completed_at. An earlier
    step ends at its last numbered message, or at the completed SessionStep.
    Without one of those, a null step_no on step 2 or later is left out.
    """
    from ..message.models import Message

    current = getattr(session, "current_step_no", None) or 0
    run_started = _exercise_run_started_at(session)
    if current <= 1:
        return run_started
    earlier_at = (
        Message.objects.filter(session=session, step_no__gte=1, step_no__lt=current)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    previous_at = (
        session.session_steps.filter(order__lt=current - 1, completed=True)
        .order_by("-order")
        .values_list("updated_at", flat=True)
        .first()
    )
    bounds = [item for item in (earlier_at, previous_at) if item is not None]
    if not bounds:
        return None
    if run_started is not None:
        bounds.append(run_started)
    return max(bounds)


def _unnumbered_user_replies(session, rows):
    """User replies saved before Message.step_no was filled in."""
    current = getattr(session, "current_step_no", None) or 0
    unnumbered = rows.filter(step_no__isnull=True)
    if current > 1:
        bound = _null_step_lower_bound(session)
        if bound is None:
            return unnumbered.none()
        return unnumbered.filter(created_at__gt=bound)
    if getattr(session, "pre_exercise_completed_at", None) is not None:
        return unnumbered.filter(created_at__gt=session.pre_exercise_completed_at)
    started = getattr(session, "created_at", None)
    if started is not None:
        return unnumbered.filter(created_at__gte=started)
    return unnumbered


def _step_user_reply_rows(session):
    """User messages in the live step, as a numbered set and an unnumbered set.

    Message.step_no is the live step copied onto each row. Check-in is 0.
    Earlier steps keep their own number. A row with no step_no is included
    only after the exercise run started, and only when that still leaves
    earlier steps out. These are the same rows _step_answer_count counts.
    """
    from ..message.models import Message

    current = getattr(session, "current_step_no", None) or 0
    if not getattr(session, "pk", None) or current < 1:
        empty = Message.objects.none()
        return empty, empty
    rows = Message.objects.filter(session=session, sender__consumer__isnull=False)
    return rows.filter(step_no=current), _unnumbered_user_replies(session, rows)


def _step_answer_count(session, user_message) -> int:
    """User replies in the current step of this exercise run, including the one just sent.

    Message.step_no is the live step copied onto each row. Check-in is 0, so
    those rows are not this step. Earlier steps keep their own number. A row
    with no step_no is counted only after the exercise run started, and only
    when that still leaves earlier steps out.
    """
    current = getattr(session, "current_step_no", None) or 0
    if current < 1:
        return 0
    numbered, unnumbered = _step_user_reply_rows(session)
    count = numbered.count() + unnumbered.count()
    if user_message is None:
        return count
    pk = getattr(user_message, "pk", None)
    if pk and (numbered.filter(pk=pk).exists() or unnumbered.filter(pk=pk).exists()):
        return count
    step_no = _stored_step_no(user_message)
    if step_no is not None:
        return count + (1 if step_no == current else 0)
    return count + 1


def step_progress_hint(session, user_message) -> str | None:
    """Once this step has had STEP_ANSWER_CAP user replies, summarise or fill the gap.

    A summary that already asks for confirmation stays put until the user agrees.
    A short yes then asks only if they are ready. Any other reply to that summary
    gets no hint. A summary already confirmed in this step is not asked for again.
    Between the two caps, one done-when check decides whether to summarise or to
    ask the one missing part. At STEP_HARD_CAP the summary is asked for anyway.
    """
    if not getattr(session, "exercise_id", None):
        return None
    try:
        in_check_in = session.in_pre_exercise_phase()
    except Exception:
        in_check_in = False
    if in_check_in:
        return None
    count = _step_answer_count(session, user_message)
    if count < STEP_ANSWER_CAP:
        return None
    from .summary_confirmation import (
        is_summary_affirmation,
        is_summary_confirmation,
        summary_was_confirmed,
    )

    previous = last_agent_message(session)
    if previous is not None and is_summary_confirmation(getattr(previous, "text", None)):
        reply = getattr(user_message, "text", None)
        if is_summary_affirmation(reply):
            return STEP_READY_HINT
        return None
    from .SessionStateMachine import _live_step

    session_step = _live_step(session)
    step = session_step.step if session_step is not None else None
    if step is not None and summary_was_confirmed(session, step):
        return None
    if count >= STEP_HARD_CAP:
        return STEP_SUMMARY_HINT
    return _capped_step_hint(session, step)


def _capped_step_hint(session, step) -> str:
    """One done-when check between the caps. A failed check still summarises."""
    if step is None:
        return STEP_SUMMARY_HINT
    from .extraction import check_done_when
    from .summary_confirmation import missing_is_only_summary_confirmation

    try:
        result = check_done_when(session, step)
    except Exception:
        logger.exception(
            "done_when check failed for session=%s step=%s",
            getattr(session, "id", None),
            getattr(step, "id", None),
        )
        return STEP_SUMMARY_HINT
    if not isinstance(result, dict):
        return STEP_SUMMARY_HINT
    if result.get("met"):
        return STEP_SUMMARY_HINT
    missing = " ".join((result.get("missing") or "").split())
    if not missing or missing_is_only_summary_confirmation(missing):
        return STEP_SUMMARY_HINT
    return STEP_MISSING_HINT.format(missing=missing)


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
    name = user_name.strip() or "there"
    wording = ABOUT_THE_USER_HINT.replace("{user_name}", name)
    return f"{wording}\n\n<ABOUT_CLIENT>\n{_about_sean_body(session)}\n</ABOUT_CLIENT>"


def _without_unknown_knowledge(context: str) -> str:
    kept = [
        line
        for line in (context or "").splitlines()
        if not line.startswith("Unknown knowledge:")
    ]
    return "\n".join(kept).strip()


def _about_sean_body(session) -> str:
    from .prompt_blocks import render_client_summary, render_knowledge, render_session_context

    consumer = session.consumer
    summary = (render_client_summary(consumer) or "").strip()
    knowledge = (render_knowledge(consumer, "general") or "").strip()
    context = _without_unknown_knowledge(render_session_context(consumer, session) or "")
    return "\n\n".join(part for part in (summary, knowledge, context) if part)


def _summary_without_account_name(summary: str) -> str:
    """Drop the leading account-name line so a new client still looks new."""
    text = (summary or "").strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("Name:"):
        return "\n".join(lines[1:]).strip()
    return text


def _client_blocks_are_new(session) -> bool:
    """True when summary, knowledge, and session context have nothing to name."""
    from .prompt_blocks import render_client_summary, render_knowledge, render_session_context

    consumer = session.consumer
    summary = _summary_without_account_name(render_client_summary(consumer) or "")
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


def last_step_hint(session) -> str:
    return LAST_STEP_HINT.format(name=_client_first_name(session))


def _client_first_name(session) -> str:
    consumer = getattr(session, "consumer", None)
    user = getattr(consumer, "user", None) if consumer is not None else None
    return (getattr(user, "first_name", None) or "").strip() or "The user"


def finish_after_confirmed_summary_hint(session) -> str | None:
    """Last step only, once the user has agreed the summary and the goal is still open."""
    if not getattr(session, "exercise_id", None):
        return None
    from .SessionStateMachine import _is_last_step, _live_step

    if not _is_last_step(session):
        return None
    session_step = _live_step(session)
    if session_step is None or session_step.goal_met_at is not None:
        return None
    from .summary_confirmation import summary_confirmation_required, summary_was_confirmed

    done_when = getattr(session_step.step, "done_when", None) or ""
    if not summary_confirmation_required(done_when):
        return None
    if not summary_was_confirmed(session, session_step.step):
        return None
    name = _client_first_name(session)
    return (
        f"{name} has confirmed the summary. Remind them briefly that they do not need to "
        "get it right every time and can come back and try the exercise again. "
        "Then ask only whether they are ready to finish. Do not say goodbye."
    )


def _with_step_sequence(session, body: str) -> str:
    """Keep an exercise turn on the next written instruction."""
    if not getattr(session, "exercise_id", None):
        return body
    try:
        in_check_in = session.in_pre_exercise_phase()
    except Exception:
        in_check_in = False
    if in_check_in:
        return body
    from .Agent import _current_step_instructions
    from .step_script import sequence_hint
    from ..message.models import Message

    instructions = _current_step_instructions(session)
    if not instructions:
        return body
    prior = list(
        Message.objects.filter(session=session, sender__agent__isnull=False)
        .order_by("created_at")
        .values_list("text", flat=True)
    )
    hint = sequence_hint(instructions, prior)
    if not hint:
        return body
    if "</TURN_HINT>" in body:
        return body.replace("</TURN_HINT>", f"\n{hint}\n</TURN_HINT>", 1)
    return f"{body}\n\n<TURN_HINT>\n{hint}\n</TURN_HINT>"


def user_prompt_with_hint(session, user_message) -> str:
    """User text plus a turn hint that is not stored on the message."""
    hinted = _hinted_user_prompt(session, user_message)
    final = _with_step_sequence(session, hinted)
    _note_hint(session, user_message, final)
    return final


def _consume_not_ready_hint(session) -> str | None:
    """One-shot hint stored when a not-ready reply goes to the chat model."""
    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    if "not_ready_hint" not in meta:
        return None
    hint = (meta.pop("not_ready_hint") or "").strip()
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    if not hint:
        return None
    from ..message.turn_prompt import note_turn_decision

    note_turn_decision(
        session,
        {
            "type": "ready_reply",
            "fired": False,
            "what": "The reply was taken as not ready.",
            "why": "The reply declines, or asks to wait.",
            "inputs": {"verdict": "no"},
        },
    )
    return hint


def _consume_offer_decline_hint(session) -> str | None:
    """One-shot hint for a tapped No. Wins over every other hint this turn."""
    from .ExerciseOffer import OFFER_DECLINE_HINT_KEY, OFFER_DECLINE_TITLE_KEY

    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    if OFFER_DECLINE_HINT_KEY not in meta:
        return None
    hint = (meta.pop(OFFER_DECLINE_HINT_KEY) or "").strip()
    title = meta.get(OFFER_DECLINE_TITLE_KEY)
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    if title:
        session._offer_decline_title = title
    return hint or None


def _hinted_user_prompt(session, user_message) -> str:
    from ..message.models import Message

    text = user_message.text or ""
    winner = None
    decline = _consume_offer_decline_hint(session)
    if decline:
        _note_thin_answer(session, user_message, "offer_decline")
        return f"{text}\n\n<TURN_HINT>\n{decline}\n</TURN_HINT>"
    not_ready = _consume_not_ready_hint(session)
    about = None if not_ready else about_the_user_hint(session, text)
    if not_ready:
        winner = "not_ready"
        body = f"{text}\n\n<TURN_HINT>\n{not_ready}\n</TURN_HINT>"
    elif about:
        winner = "about_the_user"
        body = f"{text}\n\n<TURN_HINT>\n{about}\n</TURN_HINT>"
    else:
        finish = finish_after_confirmed_summary_hint(session)
        if finish:
            _consume_goal_hint(session)
            winner = "finish_summary"
            body = f"{text}\n\n<TURN_HINT>\n{finish}\n</TURN_HINT>"
        else:
            goal = _consume_goal_hint(session)
            if goal:
                winner = "goal"
                body = f"{text}\n\n<TURN_HINT>\n{goal}\n</TURN_HINT>"
            else:
                progress = step_progress_hint(session, user_message)
                if progress:
                    winner = "step_progress"
                    body = f"{text}\n\n<TURN_HINT>\n{progress}\n</TURN_HINT>"
                else:
                    depth = _consume_depth_hint(session)
                    if depth:
                        winner = "depth"
                        body = f"{text}\n\n<TURN_HINT>\n{depth}\n</TURN_HINT>"
                    else:
                        previous = (
                            Message.objects.filter(session=session, sender__agent__isnull=False)
                            .order_by("-created_at")
                            .first()
                        )
                        hint = turn_hint_text(previous, text, session)
                        if hint:
                            winner = "thin_answer"
                            body = f"{text}\n\n<TURN_HINT>\n{hint}\n</TURN_HINT>"
                        else:
                            nudge = _exercise_nudge_hint(session, user_message)
                            if nudge:
                                winner = "exercise_nudge"
                                body = f"{text}\n\n<TURN_HINT>\n{nudge}\n</TURN_HINT>"
                            else:
                                body = text
    _note_thin_answer(session, user_message, winner)
    return body


def _note_thin_answer(session, user_message, winner: str | None) -> None:
    from ..message.turn_prompt import note_turn_decision, turn_prompts_enabled
    from ..setting.models import Setting

    if not turn_prompts_enabled():
        return
    if not Setting.get_thin_answer_hint_enabled():
        note_turn_decision(
            session,
            {
                "type": "thin_answer",
                "fired": False,
                "what": "No thin-answer hint was added.",
                "why": "Thin-answer hint is switched off in settings.",
                "inputs": {"thin": False},
            },
        )
        return
    text = getattr(user_message, "text", None) or ""
    word_count = len(text.split()) if text.strip() else 0
    min_words = Setting.get_thin_answer_min_words()
    previous = last_agent_message(session)
    probe_count = int(getattr(previous, "probe_count", 0) or 0) if previous is not None else 0
    kind = normalize_question_kind(getattr(previous, "question_kind", None) if previous else None)
    thin = bool(previous is not None and is_thin_answer(text))
    fired = winner == "thin_answer"
    if fired and probe_count >= 2:
        what = "The thin-answer hint accepted the reply."
        why = "The open question had already been followed up twice."
    elif fired:
        what = "The thin-answer hint asked for one follow-up."
        why = "The previous question was open and this reply was thin."
    elif winner:
        what = "The thin-answer check was not used."
        why = "An earlier hint was chosen."
    else:
        what = "No thin-answer hint was added."
        why = "The previous question was not open, or the reply was not thin."
    note_turn_decision(
        session,
        {
            "type": "thin_answer",
            "fired": fired,
            "what": what,
            "why": why,
            "inputs": {
                "word_count": word_count,
                "min_words": min_words,
                "probe_count": probe_count,
                "question_kind": kind,
                "thin": thin,
            },
        },
    )


def _note_hint(session, user_message, prompted: str) -> None:
    from ..message.debug_payload import hint_ladder
    from ..message.turn_prompt import note_turn_decision, turn_prompts_enabled

    if not turn_prompts_enabled():
        return
    ladder = hint_ladder(prompted)
    winner = ladder.get("winner")
    sequence = "The next part is:" in (prompted or "")
    if winner and sequence:
        what = "A priority hint was added, then the next step line."
        why = "The ladder chose a hint, and the step still had a next instruction."
    elif winner:
        what = "A priority hint was added."
        why = next(
            (row["reason"] for row in ladder["candidates"] if row.get("won")),
            "A hint from the ladder was used.",
        )
    elif sequence:
        what = "The next step line was added."
        why = "No ladder hint applied, and the step still had a next instruction."
    else:
        what = "No turn hint was added."
        why = "None of the ladder hints applied."
    note_turn_decision(
        session,
        {
            "type": "hint",
            "fired": bool(winner or sequence),
            "what": what,
            "why": why,
            "inputs": {"winner": winner, "sequence": sequence},
        },
    )


def _exercise_nudge_hint(session, user_message) -> str | None:
    """One general-chat nudge after N person messages, then one more, then stop."""
    if getattr(session, "exercise_id", None):
        return None
    from ..setting.models import Setting

    if not Setting.get_exercise_nudge_enabled():
        return None
    from .ExerciseOffer import OFFER_DECLINE_HINT_KEY, OFFER_DECLINE_TITLE_KEY

    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    if OFFER_DECLINE_HINT_KEY in meta or OFFER_DECLINE_TITLE_KEY in meta:
        return None
    if getattr(session, "_offer_decline_title", None):
        return None
    if _nudge_blocked_by_risk(session, getattr(user_message, "text", None) or ""):
        return None
    if _offer_already_recorded(session):
        return None
    try:
        sent = int(meta.get(_NUDGES_SENT_KEY) or 0)
    except (TypeError, ValueError):
        sent = 0
    if sent >= _EXERCISE_NUDGE_LIMIT:
        return None
    count = _person_message_count(session, user_message)
    if sent == 0:
        if count < Setting.get_exercise_nudge_after_messages():
            return None
    else:
        try:
            last_at = int(meta.get(_NUDGE_LAST_AT_KEY) or 0)
        except (TypeError, ValueError):
            last_at = 0
        if count < last_at + _EXERCISE_NUDGE_GAP:
            return None
    sent += 1
    meta[_NUDGES_SENT_KEY] = sent
    meta[_NUDGE_LAST_AT_KEY] = count
    session.cached_prompt_meta = meta
    if getattr(session, "pk", None):
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
    logger.info(
        "general-chat exercise nudge session=%s message=%s count=%s",
        getattr(session, "id", None),
        getattr(user_message, "id", None),
        sent,
    )
    return EXERCISE_NUDGE_HINT


def _person_message_count(session, user_message) -> int:
    """This person's saved messages in the session, including the one just sent."""
    from ..message.models import Message

    count = Message.objects.filter(
        session=session,
        sender__consumer__isnull=False,
    ).count()
    if not getattr(user_message, "pk", None):
        return count + 1
    if not Message.objects.filter(pk=user_message.pk).exists():
        return count + 1
    return count


def _offer_already_recorded(session) -> bool:
    """True when this session has offered, declined, or accepted an exercise.

    Offer memory keeps the last five rows and does not drop them when the
    six-turn prompt window passes. A message that still points at an exercise
    counts too, including one that has aged out of that list.
    """
    for row in (getattr(session, "cached_prompt_meta", None) or {}).get("exercise_offers") or []:
        if isinstance(row, dict) and row.get("outcome") in {"offered", "declined", "accepted"}:
            return True
    from ..message.models import Message

    return Message.objects.filter(session=session, exercise__isnull=False).exists()


def _nudge_blocked_by_risk(session, text: str) -> bool:
    if getattr(session, "closed_at", None):
        return True
    live = (getattr(session, "live_risk_level", None) or "").strip().lower()
    if live and live != Constants.LIVE_RISK_LEVEL_NONE:
        return True
    nightly = (getattr(session, "risk_level", None) or "").strip().lower()
    if nightly in (
        Constants.RISK_LEVEL_MODERATE,
        Constants.RISK_LEVEL_HIGH,
        Constants.RISK_LEVEL_CRITICAL,
    ):
        return True
    from .risk import risk_prescreen

    return risk_prescreen(text) != Constants.LIVE_RISK_LEVEL_NONE


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
