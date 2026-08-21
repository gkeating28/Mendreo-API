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
    shapes the message that is persisted for the client.
    """
    if exercise and not session.exercise_id:
        return list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES)
    return None


def _normalize_offer_text(text: str) -> str:
    return (text or "").lower().replace("\u2019", "'").replace("\u2018", "'")


def already_invites_exercise_start(text: str | None) -> bool:
    """True when Toni already named the exercise and asked to start it."""
    lower = _normalize_offer_text(text or "")
    return (
        "would you like to start" in lower
        or "let's work through" in lower
        or "lets work through" in lower
        or "tap below to start" in lower
        or "tap to start" in lower
    )


def with_offer_question(text: str | None, exercise) -> str:
    ask = (
        f"There's an exercise that fits what you're describing — {exercise.title}. "
        "Would you like to start an exercise? Yes or no."
    )
    body = (text or "").strip()
    if already_invites_exercise_start(body):
        return body
    return f"{body}\n\n{ask}" if body else ask


def format_agent_offer(response, exercise, session) -> tuple[list | None, str]:
    """Return (suggested_responses, text) for the persisted agent message."""
    chips = force_offer_suggested_responses(exercise, session)
    if chips is None:
        return response.suggested_responses, response.text
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
    """Latest offer whose exercise has not been started as a session yet.

    Used when the user already tapped Yes (chips cleared) then declines
    from the offer sheet. Does not create a new session status.
    """
    offers = Message.objects.filter(
        session=session,
        exercise_id__isnull=False,
        sender__agent__isnull=False,
    ).order_by("-created_at")

    for offer in offers:
        started = Session.objects.filter(
            consumer_id=session.consumer_id,
            exercise_id=offer.exercise_id,
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
    cache = serializer.context.setdefault("exercise_sessions_by_id", {})
    if message.exercise_id not in cache:
        consumer_id = getattr(message.session, "consumer_id", None)
        cache[message.exercise_id] = serialize_exercise_session(
            latest_exercise_session(consumer_id, message.exercise_id)
        )
    return cache[message.exercise_id]


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
        if text != Constants.EXERCISE_OFFER_NO:
            return None
        offer = unresolved_offer_message(session)

    if offer is None:
        return None

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
            session.save(
                update_fields=[
                    "last_message",
                    "messages_no",
                    "consumer_messages_no",
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
            text=(
                f"Okay — I'll leave {title} here until you want it. "
                "Tap the card whenever you're ready."
            ),
            reasoning="Exercise offer declined",
            suggested_responses=[],
        )
        session.last_message = agent_message
        session.messages_no += 2
        session.consumer_messages_no += 1
        session.agent_messages_no += 1
        session.save(
            update_fields=[
                "last_message",
                "messages_no",
                "consumer_messages_no",
                "agent_messages_no",
                "updated_at",
            ]
        )
        return agent_message
