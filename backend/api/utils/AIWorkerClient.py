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


def request_agent_response(user_message: Message, session) -> Message:
    """Run AI chat locally or delegate to the long-running worker service."""
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
    """Generate the opening exercise greeting locally or via the worker."""
    if not session.exercise_id:
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

    message = Message(
        session=session,
        sender=consumer_participant,
        text="Hi, I'd like to practise this exercise. Can you greet me and explain the exercise please?",
    )
    agent_message = Agent.get_response(user_message=message, session=session)
    session.last_message = agent_message
    session.messages_no += 1
    session.agent_messages_no += 1
    session.save()
    return agent_message
