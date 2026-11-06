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
    "and their alternative action in their own words and ask if you have it right. "
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
    "things from it. Do not say you have no information. Then ask one simple question."
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


def turn_hint_text(previous, user_text: str) -> str | None:
    """Hint for this model call only. None unless the previous question was open."""
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


def _hinted_user_prompt(session, user_message) -> str:
    from ..message.models import Message

    text = user_message.text or ""
    winner = None
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
                    hint = turn_hint_text(previous, text)
                    if hint:
                        winner = "thin_answer"
                        body = f"{text}\n\n<TURN_HINT>\n{hint}\n</TURN_HINT>"
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
