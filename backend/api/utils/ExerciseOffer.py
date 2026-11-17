import re

from django.db import transaction

from ..message.models import Message
from ..participant.models import Participant
from ..session.models import Session
from . import Constants


def is_yes_no_offer(suggested_responses) -> bool:
    if not suggested_responses:
        return False
    return (
        Constants.EXERCISE_OFFER_YES in suggested_responses
        and Constants.EXERCISE_OFFER_NO in suggested_responses
    )


def force_offer_suggested_responses(exercise, session) -> list | None:
    """Yes/No chips when Toni attaches an exercise in general chat.

    Decision of *whether* to attach an exercise is unchanged; this only
    shapes the message that is persisted for the client. A chat linked to
    a finished run never gets that offer.
    """
    if getattr(session, "source_run_id", None):
        return None
    if exercise and not session.exercise_id:
        return list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES)
    return None


def _normalize_offer_text(text: str) -> str:
    return (text or "").lower().replace("\u2019", "'").replace("\u2018", "'")


_START_INVITE_MARKERS = (
    "would you like to start",
    "would you like to begin",
    "would you like to try",
    "let's work through",
    "lets work through",
    "tap below to start",
    "tap to start",
    "begin this exercise",
    "start this exercise",
    "ready to start",
    "ready to begin",
)


def already_invites_exercise_start(text: str | None) -> bool:
    """True when Toni already named the exercise and asked to start it."""
    lower = _normalize_offer_text(text or "")
    return any(marker in lower for marker in _START_INVITE_MARKERS)


# Small on purpose. A hit costs one tool-less retry, so keep this list tight.
UNAUTHORISED_OFFER_PHRASES = (
    "would you like to try",
    "want to try",
    "i'd suggest the",
    "i would suggest the",
    "i'd suggest an exercise",
    "i would suggest an exercise",
)

_EXERCISE_QUESTION_STARTS = (
    "what ",
    "what's ",
    "whats ",
    "how ",
    "why ",
    "when ",
    "where ",
    "who ",
    "can you ",
    "could you ",
    "tell me ",
    "explain ",
)


def _published_exercise_titles() -> list[str]:
    from ..exercise.models import Exercise

    titles = Exercise.objects.filter(
        status=Constants.EXERCISE_STATUS_PUBLISHED,
        authoring_snapshot=False,
    ).values_list("title", flat=True)
    return [title.strip() for title in titles if title and len(title.strip()) >= 3]


def _offer_phrase_hit(text: str) -> bool:
    lower = _normalize_offer_text(text)
    return any(phrase in lower for phrase in UNAUTHORISED_OFFER_PHRASES)


def _title_hit(text: str, titles: list[str]) -> bool:
    return any(title in (text or "") for title in titles)


def _user_asked_about_exercise(user_text: str, titles: list[str]) -> bool:
    raw = user_text or ""
    lower = _normalize_offer_text(raw)
    asks = "?" in raw or any(lower.startswith(prefix) for prefix in _EXERCISE_QUESTION_STARTS)
    if not asks:
        return False
    if "exercise" in lower:
        return True
    return any(title.lower() in lower for title in titles)


def reply_offers_an_exercise(reply: str | None, user_text: str | None = None) -> bool:
    """True when a general-chat reply offers an exercise without the tool.

    An exact published title counts, as does one phrase in
    ``UNAUTHORISED_OFFER_PHRASES``. A reply that only answers a question the
    person asked about an exercise does not.
    """
    body = reply or ""
    if not body.strip():
        return False
    titles = _published_exercise_titles()
    phrases = _offer_phrase_hit(body)
    if _user_asked_about_exercise(user_text or "", titles) and not phrases:
        return False
    return phrases or _title_hit(body, titles)


def without_unauthorised_offer_sentences(reply: str | None, user_text: str | None = None) -> str | None:
    """Drop offer sentences when a normal sentence is left. Otherwise None."""
    parts = re.split(r"(?<=[.!?])\s+", (reply or "").strip())
    sentences = [part.strip() for part in parts if part.strip()]
    if len(sentences) < 2:
        return None
    kept = [
        sentence for sentence in sentences
        if not reply_offers_an_exercise(sentence, user_text)
    ]
    if not kept or len(kept) == len(sentences):
        return None
    cleaned = " ".join(kept).strip()
    if not cleaned or reply_offers_an_exercise(cleaned, user_text):
        return None
    return cleaned


def with_offer_question(text: str | None, exercise) -> str:
    title = (getattr(exercise, "title", None) or "").strip() or "that exercise"
    ask = (
        f"There's an exercise that fits what you're describing: {title}. "
        "Would you like to start an exercise? Yes or no."
    )
    body = (text or "").strip()
    if not body:
        return ask
    if title in body:
        return body
    nudge = f"Would you like to try {title}? Yes or no."
    if body[-1] not in ".?!":
        body = f"{body}."
    return f"{body} {nudge}"


_OFFER_MEMORY_LIMIT = 5
_OFFER_MEMORY_TURNS = 6
_OFFER_OUTCOMES = ("offered", "declined", "accepted")


def remember_exercise_offer(session, exercise, outcome: str) -> None:
    """Record an offer on the session. The caller saves."""
    if session is None or exercise is None or not getattr(exercise, "id", None):
        return
    if getattr(session, "exercise_id", None) or getattr(session, "source_run_id", None):
        return
    if outcome not in _OFFER_OUTCOMES:
        return
    title = (getattr(exercise, "title", None) or "").replace("\n", " ").strip()
    try:
        at_count = int(session.consumer_messages_no or 0)
    except (TypeError, ValueError):
        at_count = 0
    meta = dict(session.cached_prompt_meta or {})
    kept = [
        row for row in (meta.get("exercise_offers") or [])
        if isinstance(row, dict) and row.get("exercise_id") != exercise.id
    ]
    kept.append({
        "exercise_id": exercise.id,
        "title": title,
        "outcome": outcome,
        "at_consumer_messages_no": at_count,
    })
    meta["exercise_offers"] = kept[-_OFFER_MEMORY_LIMIT:]
    session.cached_prompt_meta = meta


def recent_exercise_offer_block(session) -> str:
    """Lines for offers still inside the six-turn window. The count is done here."""
    if getattr(session, "exercise_id", None) or getattr(session, "source_run_id", None):
        return ""
    try:
        current = int(session.consumer_messages_no or 0)
    except (TypeError, ValueError):
        return ""
    lines = []
    for row in (session.cached_prompt_meta or {}).get("exercise_offers") or []:
        if not isinstance(row, dict):
            continue
        try:
            at_count = int(row.get("at_consumer_messages_no"))
        except (TypeError, ValueError):
            continue
        turns = current - at_count
        if turns < 0 or turns >= _OFFER_MEMORY_TURNS:
            continue
        title = str(row.get("title") or "").strip()
        outcome = str(row.get("outcome") or "").strip()
        if not title or outcome not in _OFFER_OUTCOMES:
            continue
        lines.append(
            f"Already in this chat: {title}, {outcome}, {turns} user turns ago. "
            "Do not offer it again yet. Stay in this chat in the same voice. "
            "Do not run an exercise here."
        )
    return "\n".join(lines)


OFFER_DECLINE_HINT_KEY = "offer_decline_hint"
OFFER_DECLINE_TITLE_KEY = "offer_decline_title"


def declined_offer_text(title: str | None) -> str:
    label = (title or "that exercise").replace("\n", " ").strip() or "that exercise"
    return f"Okay. I'll leave {label} here until you want it."


def offer_decline_hint(title: str | None) -> str:
    label = (title or "that exercise").replace("\n", " ").strip() or "that exercise"
    return (
        f'The person declined the offered exercise "{label}". '
        "Accept it in a sentence in your usual voice. "
        "Do not re-offer it or any exercise this turn. "
        "Carry on the conversation."
    )


def prepare_tapped_decline(user_message: Message) -> bool:
    """Record a tapped No and store its one-shot hint. The model then replies.

    False when this tap is not an open exercise offer. Voice still uses
    ``_resolve_offer`` and is not changed here.
    """
    session = user_message.session
    if getattr(session, "exercise_id", None):
        return False
    if (user_message.text or "").strip() != Constants.EXERCISE_OFFER_NO:
        return False
    offer = pending_offer_message(session)
    if offer is not None and not is_yes_no_offer(offer.suggested_responses):
        offer = None
    if offer is None:
        offer = unresolved_offer_message(session)
    if offer is None or not offer.exercise_id:
        return False
    if offer.suggested_responses:
        offer.suggested_responses = []
        offer.save(update_fields=["suggested_responses", "updated_at"])
    title = offer.exercise.title if offer.exercise_id else "that exercise"
    # Stamp the count the old canned path stored, after this tap is included.
    # The normal reply path increments the session once, so the field itself
    # stays where it is.
    previous_count = session.consumer_messages_no
    try:
        session.consumer_messages_no = int(previous_count or 0) + 1
    except (TypeError, ValueError):
        session.consumer_messages_no = 1
    remember_exercise_offer(session, offer.exercise, "declined")
    session.consumer_messages_no = previous_count
    meta = dict(session.cached_prompt_meta or {})
    meta[OFFER_DECLINE_HINT_KEY] = offer_decline_hint(title)
    meta[OFFER_DECLINE_TITLE_KEY] = (title or "that exercise").replace("\n", " ").strip()
    session.cached_prompt_meta = meta
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    return True


def take_offer_decline_title(session) -> str | None:
    """Drop the one-shot decline marker. The title is for the canned fallback."""
    meta = dict(getattr(session, "cached_prompt_meta", None) or {})
    title = meta.pop(OFFER_DECLINE_TITLE_KEY, None)
    had_hint = OFFER_DECLINE_HINT_KEY in meta
    if had_hint:
        meta.pop(OFFER_DECLINE_HINT_KEY, None)
    pending = getattr(session, "_offer_decline_title", None)
    if title is None and not had_hint and not pending:
        return None
    session.cached_prompt_meta = meta
    session._offer_decline_title = None
    if getattr(session, "pk", None):
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
    label = title or pending
    if not label:
        return None
    return str(label).replace("\n", " ").strip() or "that exercise"


def note_unresolved_typed_decline(session, text: str) -> None:
    """Store a typed no before the next prompt is built."""
    if getattr(session, "exercise_id", None) or getattr(session, "source_run_id", None):
        return
    if (getattr(session, "cached_prompt_meta", None) or {}).get(OFFER_DECLINE_TITLE_KEY):
        return
    if spoken_offer_chip(text or "") != Constants.EXERCISE_OFFER_NO:
        return
    offer = unresolved_offer_message(session)
    if offer is None or not offer.exercise_id:
        return
    remember_exercise_offer(session, offer.exercise, "declined")
    session.save(update_fields=["cached_prompt_meta", "updated_at"])


def format_agent_offer(response, exercise, session) -> tuple[list | None, str]:
    """Return (suggested_responses, text) for the persisted agent message."""
    from .SuggestedResponses import sanitize_suggested_responses

    chips = force_offer_suggested_responses(exercise, session)
    if chips is None:
        return (
            sanitize_suggested_responses(response.suggested_responses, response.text),
            response.text,
        )
    remember_exercise_offer(session, exercise, "offered")
    session.save(update_fields=["cached_prompt_meta", "updated_at"])
    return chips, with_offer_question(response.text, exercise)


def pending_offer_message(session: Session) -> Message | None:
    """Latest Toni offer still showing Yes/No chips."""
    return (
        Message.objects.filter(
            session=session,
            exercise_id__isnull=False,
            sender__agent__isnull=False,
            suggested_responses__contains=[Constants.EXERCISE_OFFER_YES],
        )
        .order_by("-created_at")
        .first()
    )


def unresolved_offer_message(session: Session) -> Message | None:
    """Latest offer whose exercise has not been started in this chat.

    Used when the user already tapped Yes (chips cleared) then declines
    from the offer sheet. Does not create a new session status.

    A general chat does not own exercise runs. A run in another chat
    does not count as this offer being started.
    """
    offers = Message.objects.filter(
        session=session,
        exercise_id__isnull=False,
        sender__agent__isnull=False,
    ).order_by("-created_at")

    if not getattr(session, "exercise_id", None):
        return offers.first()

    for offer in offers:
        started = Session.objects.filter(
            consumer_id=session.consumer_id,
            exercise_id=offer.exercise_id,
            authoring_test=False,
        ).exists()
        if not started:
            return offer
    return None


def latest_exercise_session(consumer_id, exercise_id) -> Session | None:
    if not consumer_id or not exercise_id:
        return None
    return (
        Session.objects.filter(
            consumer_id=consumer_id,
            exercise_id=exercise_id,
            abandoned=False,
            authoring_test=False,
        )
        .order_by("-created_at")
        .only("id", "completed", "current_step_no", "total_steps_no")
        .first()
    )


def serialize_exercise_session(session: Session | None) -> dict | None:
    if not session:
        return None
    return {
        "id": session.id,
        "completed": session.completed,
        "current_step_no": session.current_step_no,
        "total_steps_no": session.total_steps_no,
    }


def exercise_session_payload_for_message(serializer, message) -> dict | None:
    if not message.exercise_id:
        return None
    # A general-chat offer keeps message.exercise. It must not inherit a run
    # from another chat. Skip the cache so a later exercise-session message
    # in the same serializer still looks up its own run.
    if not getattr(getattr(message, "session", None), "exercise_id", None):
        return None
    cache = serializer.context.setdefault("exercise_sessions_by_id", {})
    if message.exercise_id not in cache:
        consumer_id = getattr(message.session, "consumer_id", None)
        cache[message.exercise_id] = serialize_exercise_session(
            latest_exercise_session(consumer_id, message.exercise_id)
        )
    return cache[message.exercise_id]


_BARE_YES_RE = re.compile(
    r"^(yes|yeah|yep|yup|sure|ok|okay|please)(\s+please)?([.!?]?)$"
)
_BARE_NO_RE = re.compile(
    r"^(no|nope|nah|no thanks|not now|not right now|maybe later|later|skip)([.!?]?)$"
)
_START_RE = re.compile(r"^(let'?s\s+)?(start|begin|do it|go ahead|let'?s go)([.!?]?)$")
_START_EXERCISE_RE = re.compile(
    r"^(start|begin)(\s+(the\s+)?(exercise|that|it|now))?([.!?]?)$"
)


def spoken_offer_chip(text: str) -> str | None:
    """Map a spoken utterance to Yes/No chips. None = not an offer reply."""
    t = _normalize_offer_text(text).strip()
    if not t:
        return None
    if _BARE_NO_RE.match(t):
        return Constants.EXERCISE_OFFER_NO
    if _BARE_YES_RE.match(t) or _START_RE.match(t) or _START_EXERCISE_RE.match(t):
        return Constants.EXERCISE_OFFER_YES
    return None


def maybe_handle_offer_response(
    user_message: Message,
    from_suggested_response: bool,
) -> Message | None:
    """Handle a Yes/No chip reply without the LLM and without starting a session.

    Typed text must not take this path — the client only sets
    ``from_suggested_response`` when a suggestion pill is tapped.

    Returns the message to send back to the client, or None to fall through
    to a normal AI turn.
    """
    if not from_suggested_response:
        return None

    session = user_message.session
    if session.exercise_id:
        return None

    text = (user_message.text or "").strip()
    if text not in Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES:
        return None

    offer = pending_offer_message(session)
    if offer is not None and not is_yes_no_offer(offer.suggested_responses):
        offer = None

    if offer is None:
        offer = unresolved_offer_message(session)
        if offer is None:
            return None
        if text == Constants.EXERCISE_OFFER_YES:
            # Chips already cleared (e.g. voice adapter + client chip POST).
            return user_message

    return _resolve_offer(user_message, offer, text)


def _resolve_offer(user_message: Message, offer: Message, text: str) -> Message:
    with transaction.atomic():
        if offer.suggested_responses:
            offer.suggested_responses = []
            offer.save(update_fields=["suggested_responses", "updated_at"])

        session = user_message.session

        if text == Constants.EXERCISE_OFFER_YES:
            session.last_message = user_message
            session.messages_no += 1
            session.consumer_messages_no += 1
            session.resume_dismissed_at = None
            if offer.exercise_id:
                remember_exercise_offer(session, offer.exercise, "accepted")
            session.save(
                update_fields=[
                    "last_message",
                    "messages_no",
                    "consumer_messages_no",
                    "resume_dismissed_at",
                    "cached_prompt_meta",
                    "updated_at",
                ]
            )
            return user_message

        agent_participant = Participant.objects.filter(
            session=session,
            agent=session.consumer.agent,
        ).first()
        title = offer.exercise.title if offer.exercise_id else "that exercise"
        agent_message = Message.objects.create(
            session=session,
            sender=agent_participant,
            text=declined_offer_text(title),
            reasoning="Exercise offer declined",
            suggested_responses=[],
        )
        session.last_message = agent_message
        session.messages_no += 2
        session.consumer_messages_no += 1
        session.agent_messages_no += 1
        session.resume_dismissed_at = None
        if offer.exercise_id:
            remember_exercise_offer(session, offer.exercise, "declined")
        session.save(
            update_fields=[
                "last_message",
                "messages_no",
                "consumer_messages_no",
                "agent_messages_no",
                "resume_dismissed_at",
                "cached_prompt_meta",
                "updated_at",
            ]
        )
        return agent_message
