import logging

import httpx
from django.conf import settings

from ..agent.models import Agent
from ..message.models import Message
from .MessageFlow import apply_agent_response

logger = logging.getLogger(__name__)


def _worker_headers() -> dict[str, str]:
    return {"X-Internal-Secret": settings.INTERNAL_API_SECRET}


def _should_delegate_to_worker() -> bool:
    return bool(settings.AI_WORKER_URL and settings.INTERNAL_API_SECRET)


def enqueue_agent_response(user_message: Message) -> None:
    """Queue AI reply on Celery (worker process runs Gemini)."""
    from ..tasks import process_agent_response
    process_agent_response.delay_on_commit(user_message.id)


def enqueue_session_greeting(session) -> None:
    from ..tasks import process_session_greeting
    process_session_greeting.delay_on_commit(session.id)


def request_agent_response(user_message: Message, session) -> Message:
    """Run AI chat locally, via worker HTTP, or enqueue for async clients.

    When ``AI_ASYNC_MESSAGES`` is enabled the caller should return the user
    message immediately after ``enqueue_agent_response``; this sync helper is
    kept for local/tests and the internal worker HTTP endpoint.
    """
    if not _should_delegate_to_worker():
        agent_message = Agent.get_response(user_message=user_message, session=session)
        return apply_agent_response(user_message, agent_message)

    url = f"{settings.AI_WORKER_URL.rstrip('/')}/internal/ai/message-response"
    try:
        response = httpx.post(
            url,
            json={"user_message_id": user_message.id},
            headers=_worker_headers(),
            timeout=settings.AI_WORKER_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("AI worker message-response failed for %s", user_message.id)
        raise

    agent_message_id = response.json()["agent_message_id"]
    return Message.objects.get(id=agent_message_id)


def request_session_greeting(session) -> Message | None:
    """Generate the opening exercise greeting locally, via worker, or enqueue."""
    if not session.exercise_id:
        return None

    if getattr(settings, "AI_ASYNC_MESSAGES", False):
        enqueue_session_greeting(session)
        return None

    if not _should_delegate_to_worker():
        return _run_session_greeting(session)

    url = f"{settings.AI_WORKER_URL.rstrip('/')}/internal/ai/session-greeting"
    try:
        response = httpx.post(
            url,
            json={"session_id": session.id},
            headers=_worker_headers(),
            timeout=settings.AI_WORKER_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("AI worker session-greeting failed for %s", session.id)
        raise

    agent_message_id = response.json()["agent_message_id"]
    session.refresh_from_db()
    return Message.objects.get(id=agent_message_id)


def _run_session_greeting(session):
    from ..participant.models import Participant

    consumer_participant = Participant.objects.filter(
        session=session,
        consumer=session.consumer,
    ).first()
    if not consumer_participant:
        return None

    if session.in_pre_exercise_phase():
        text = (
            "Hi, I'd like to practise this exercise again. "
            "Please start with the pre-exercise check-in before we begin Step 1."
        )
    else:
        text = (
            "Hi, I'd like to practise this exercise. "
            "Can you greet me and explain the exercise please?"
        )

    message = Message(
        session=session,
        sender=consumer_participant,
        text=text,
    )
    agent_message = Agent.get_response(user_message=message, session=session)
    session.last_message = agent_message
    session.messages_no += 1
    session.agent_messages_no += 1
    session.save(update_fields=["last_message", "messages_no", "agent_messages_no", "updated_at"])
    return agent_message
