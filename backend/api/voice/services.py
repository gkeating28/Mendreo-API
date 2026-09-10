"""Voice session minting, Custom LLM adapter, and post-call reconcile."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import Iterable

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..agent.models import Agent
from ..message.models import Message
from ..participant.models import Participant
from ..session.models import Session
from ..utils.ExerciseOffer import (
    maybe_handle_offer_response,
    pending_offer_message,
    spoken_offer_chip,
    unresolved_offer_message,
)
from ..utils.MessageFlow import apply_agent_response
from .elevenlabs_client import mint_conversation_credentials
from .models import VoiceGrant, hash_grant_token

logger = logging.getLogger(__name__)

GENERAL_CHAT_ONLY = "Voice is only available for general chat."
VOICE_DUPLICATE_WINDOW = timedelta(seconds=20)
# ElevenLabs cascade_timeout_seconds defaults to 8s. Emit this before Gemini
# so time-to-first-token is immediate. Trailing space keeps TTS from gluing
# the real reply onto the ellipsis.
ELEVENLABS_KEEPALIVE = "... "
_HAS_SPEECH_RE = re.compile(r"[A-Za-z0-9]")
_SESSION_THREAD_LOCKS: dict[str, threading.Lock] = {}
_SESSION_THREAD_GUARDS = threading.Lock()


def _json_obj(value):
    return value if isinstance(value, dict) else {}


def extra_body_from_request(data: dict) -> dict:
    extra = data.get("elevenlabs_extra_body")
    if extra is None:
        extra = data.get("custom_llm_extra_body")
    return _json_obj(extra)


def extract_grant_token(data: dict) -> str | None:
    extra = extra_body_from_request(data)
    grant = extra.get("grant")
    if isinstance(grant, str) and grant.strip():
        return grant.strip()
    return None


def extract_conversation_id(data: dict) -> str | None:
    extra = extra_body_from_request(data)
    for source in (extra, data):
        for key in (
            "conversation_id",
            "conversationId",
            "elevenlabs_conversation_id",
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def latest_user_text(messages) -> str:
    """Last user turn only. Empty last turns must not fall back to earlier speech."""
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if not isinstance(item, dict):
            continue
        if (item.get("role") or "").lower() != "user":
            continue
        return _message_content_text(item.get("content"))
    return ""


def usable_voice_user_text(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned or not _HAS_SPEECH_RE.search(cleaned):
        return ""
    return cleaned


def spoken_llm_keepalive() -> str:
    filler = (settings.ELEVENLABS_LLM_FILLER or "").strip()
    if filler:
        return filler if filler.endswith(" ") else f"{filler} "
    return ELEVENLABS_KEEPALIVE


def _session_lock_key(session_id: str) -> int:
    digest = hashlib.sha256(str(session_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextmanager
def session_generation_lock(session_id: str):
    """Serialize Gemini for one chat session across Gunicorn workers."""
    if connection.vendor == "postgresql":
        key = _session_lock_key(session_id)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [key])
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
        return

    with _SESSION_THREAD_GUARDS:
        lock = _SESSION_THREAD_LOCKS.setdefault(str(session_id), threading.Lock())
    with lock:
        yield


def _message_content_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        nested = content.get("text") or content.get("content")
        if isinstance(nested, str):
            return nested.strip()
        if isinstance(nested, list):
            return _message_content_text(nested)
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block.strip())
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def require_general_session(session: Session) -> None:
    if session.exercise_id:
        raise ValidationError({"detail": GENERAL_CHAT_ONLY})
    if session.completed:
        raise ValidationError({"detail": "This session is no longer active."})


def resolve_general_session(consumer, session_id: str | None) -> Session:
    if session_id:
        session = Session.objects.filter(id=session_id, consumer=consumer).first()
        if session is None:
            raise ValidationError({"session_id": "Session not found."})
        require_general_session(session)
        return session
    session = Session.get_or_create(consumer)
    require_general_session(session)
    return session


def mint_voice_token(consumer, session_id: str | None = None) -> dict:
    session = resolve_general_session(consumer, session_id)
    credentials = mint_conversation_credentials()
    grant, raw_token = VoiceGrant.issue(consumer=consumer, session=session)
    return {
        "conversation_token": credentials.get("conversation_token"),
        "signed_url": credentials.get("signed_url"),
        "session_id": session.id,
        "expires_at": grant.expires_at,
        "custom_llm_extra_body": {"grant": raw_token},
    }


def resolve_usable_grant(raw_token: str | None) -> VoiceGrant:
    grant = VoiceGrant.resolve(raw_token)
    if grant is None:
        raise PermissionDenied("Invalid or expired voice grant")
    if grant.consumer_id != grant.session.consumer_id:
        raise PermissionDenied("Invalid voice grant")
    require_general_session(grant.session)
    return grant


def stamp_conversation_id(grant: VoiceGrant, conversation_id: str | None) -> VoiceGrant:
    if not conversation_id:
        return grant
    with transaction.atomic():
        locked = VoiceGrant.objects.select_for_update().get(pk=grant.pk)
        existing = locked.elevenlabs_conversation_id
        if existing and existing != conversation_id:
            raise PermissionDenied("Voice grant does not match this conversation")
        if not existing:
            locked.elevenlabs_conversation_id = conversation_id
            locked.save(update_fields=["elevenlabs_conversation_id", "updated_at"])
            Message.objects.filter(
                session_id=locked.session_id,
                voice_conversation_id=f"grant:{locked.id}",
            ).update(voice_conversation_id=conversation_id)
        grant.elevenlabs_conversation_id = locked.elevenlabs_conversation_id
    return grant


def _consumer_participant(session, consumer) -> Participant:
    participant = Participant.objects.filter(session=session, consumer=consumer).first()
    if participant is None:
        raise ValidationError({"detail": "You are not a participant in this session."})
    return participant


def _agent_participant(session, consumer) -> Participant:
    participant = Participant.objects.filter(session=session, agent=consumer.agent).first()
    if participant is None:
        raise ValidationError({"detail": "Agent participant is missing for this session."})
    return participant


def voice_conversation_key(grant: VoiceGrant) -> str:
    return grant.elevenlabs_conversation_id or f"grant:{grant.id}"


def next_voice_turn_index(session, conversation_key: str) -> int:
    current = (
        Message.objects.filter(
            session=session,
            voice_conversation_id=conversation_key,
            voice_turn_index__isnull=False,
        )
        .order_by("-voice_turn_index")
        .values_list("voice_turn_index", flat=True)
        .first()
    )
    return 0 if current is None else int(current) + 1


def create_user_voice_message(*, grant: VoiceGrant, text: str) -> Message:
    session = grant.session
    consumer = grant.consumer
    participant = _consumer_participant(session, consumer)
    conversation_key = voice_conversation_key(grant)
    turn_index = next_voice_turn_index(session, conversation_key)
    return Message.objects.create(
        session=session,
        sender=participant,
        text=text,
        voice_conversation_id=conversation_key,
        voice_turn_index=turn_index,
    )


def stamp_agent_voice_fields(agent_message: Message, grant: VoiceGrant) -> Message:
    conversation_key = voice_conversation_key(grant)
    if agent_message.voice_conversation_id and agent_message.voice_turn_index is not None:
        return agent_message
    turn_index = next_voice_turn_index(agent_message.session, conversation_key)
    agent_message.voice_conversation_id = conversation_key
    agent_message.voice_turn_index = turn_index
    agent_message.save(update_fields=["voice_conversation_id", "voice_turn_index", "updated_at"])
    return agent_message


def run_toni_reply(grant: VoiceGrant, user_text: str) -> Message:
    """
    Same Gemini path as text chat: Agent.get_response + apply_agent_response.

    Neither helper reads the HTTP request or JWT — they only need Session + Message.
    Do not call POST /messages (that would enqueue/double-fire Gemini).
    """
    session = Session.objects.select_related("consumer", "consumer__agent").get(pk=grant.session_id)
    session.refresh_from_db(fields=["cached_history", "cached_prompt"])
    user_message = create_user_voice_message(grant=grant, text=user_text)
    agent_message = Agent.get_response(session=session, user_message=user_message)
    apply_agent_response(user_message, agent_message)
    return stamp_agent_voice_fields(agent_message, grant)


def sse_chunk(content: str | None, *, finish_reason=None, chunk_id: str, created: int, model: str) -> bytes:
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content is not None else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def iter_silent_completion_sse() -> Iterable[bytes]:
    """Acknowledge a non-turn (silence / duplicate) without calling Gemini."""
    created = int(time.time())
    chunk_id = "chatcmpl-silent"
    model = "mendreo-toni"
    yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
    yield b"data: [DONE]\n\n"


def is_repeat_voice_utterance(grant: VoiceGrant, user_text: str) -> bool:
    last = (
        Message.objects.filter(
            session=grant.session,
            sender__consumer=grant.consumer,
            voice_conversation_id=voice_conversation_key(grant),
        )
        .order_by("-created_at")
        .first()
    )
    if last is None:
        return False
    if (last.text or "").strip() != user_text.strip():
        return False
    return last.created_at >= timezone.now() - VOICE_DUPLICATE_WINDOW


def try_voice_offer_reply(grant: VoiceGrant, user_text: str) -> Message | None:
    """Route spoken Yes/No through the chip handler. None = not an offer turn."""
    chip = spoken_offer_chip(user_text)
    if not chip or grant.session.exercise_id:
        return None
    if pending_offer_message(grant.session) is None and unresolved_offer_message(grant.session) is None:
        return None
    user_message = create_user_voice_message(grant=grant, text=chip)
    result = maybe_handle_offer_response(user_message, True)
    return result if result is not None else user_message


def iter_completion_sse(grant: VoiceGrant, user_text: str) -> Iterable[bytes]:
    created = int(time.time())
    chunk_id = f"chatcmpl-{grant.id}"
    model = "mendreo-toni"

    try:
        if is_repeat_voice_utterance(grant, user_text):
            yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
            yield b"data: [DONE]\n\n"
            return

        offer_result = try_voice_offer_reply(grant, user_text)
        if offer_result is not None:
            spoken = ""
            if getattr(offer_result.sender, "agent_id", None):
                spoken = (offer_result.text or "").strip()
            if spoken:
                yield sse_chunk(spoken, chunk_id=chunk_id, created=created, model=model)
            yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
            yield b"data: [DONE]\n\n"
            return

        keepalive = spoken_llm_keepalive()
        yield sse_chunk(keepalive, chunk_id=chunk_id, created=created, model=model)

        with session_generation_lock(grant.session_id):
            agent_message = run_toni_reply(grant, user_text)
        text = (agent_message.text or "").strip()
        if text:
            yield sse_chunk(text, chunk_id=chunk_id, created=created, model=model)
        yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
        yield b"data: [DONE]\n\n"
    except Exception:
        logger.exception(
            "Custom LLM Gemini path failed grant=%s session=%s",
            grant.id,
            grant.session_id,
        )
        fallback = "Sorry, I had an issue understanding your message, can you repeat it or rephrase it for me please?"
        yield sse_chunk(fallback, chunk_id=chunk_id, created=created, model=model)
        yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
        yield b"data: [DONE]\n\n"


def _turn_role(turn: dict) -> str:
    role = (turn.get("role") or turn.get("source") or "").lower()
    if role in ("user", "customer"):
        return "user"
    if role in ("agent", "assistant", "ai"):
        return "agent"
    return role


def _turn_text(turn: dict) -> str:
    for key in ("message", "text", "content"):
        value = turn.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_user_sender(message: Message) -> bool:
    return bool(getattr(message.sender, "consumer_id", None))


def _grant_from_webhook_payload(conversation_id: str, payload: dict) -> VoiceGrant | None:
    grant = (
        VoiceGrant.objects.select_related("consumer", "session", "consumer__agent")
        .filter(elevenlabs_conversation_id=conversation_id)
        .order_by("-created_at")
        .first()
    )
    if grant:
        return grant

    init = payload.get("conversation_initiation_client_data") or {}
    extra = (
        init.get("custom_llm_extra_body")
        or init.get("elevenlabs_extra_body")
        or extra_body_from_request(payload)
        or {}
    )
    if not isinstance(extra, dict):
        extra = {}
    raw = extra.get("grant")
    if not raw:
        variables = init.get("dynamic_variables") or payload.get("dynamic_variables") or {}
        if isinstance(variables, dict):
            raw = variables.get("grant")
    if not raw or not isinstance(raw, str):
        return None
    hashed = hash_grant_token(raw.strip())
    return (
        VoiceGrant.objects.select_related("consumer", "session", "consumer__agent")
        .filter(token_hash=hashed)
        .first()
    )


def reconcile_post_call_transcript(*, conversation_id: str, transcript, payload=None) -> dict:
    if not conversation_id:
        return {"status": "ignored", "reason": "missing_conversation_id", "created": 0, "stamped": 0}

    grant = _grant_from_webhook_payload(conversation_id, payload or {})
    if grant is None:
        return {"status": "ignored", "reason": "unknown_conversation", "created": 0, "stamped": 0}

    if not grant.elevenlabs_conversation_id:
        try:
            stamp_conversation_id(grant, conversation_id)
            grant.refresh_from_db()
        except PermissionDenied:
            return {"status": "ignored", "reason": "conversation_mismatch", "created": 0, "stamped": 0}

    session = grant.session
    consumer = grant.consumer
    created = 0
    stamped = 0
    turns = transcript if isinstance(transcript, list) else []

    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        text = _turn_text(turn)
        role = _turn_role(turn)
        if not text or role not in ("user", "agent"):
            continue

        existing = (
            Message.objects.filter(session=session, voice_turn_index=index)
            .filter(
                Q(voice_conversation_id=conversation_id)
                | Q(voice_conversation_id=f"grant:{grant.id}")
            )
            .select_related("sender")
            .first()
        )
        if existing:
            continue

        untagged = (
            Message.objects.filter(session=session, text=text)
            .filter(
                Q(voice_turn_index__isnull=True)
                | Q(voice_conversation_id=f"grant:{grant.id}")
            )
            .select_related("sender")
            .order_by("created_at")
        )
        matched = None
        for message in untagged:
            if role == "user" and _is_user_sender(message):
                matched = message
                break
            if role == "agent" and not _is_user_sender(message):
                matched = message
                break
        if matched:
            matched.voice_conversation_id = conversation_id
            matched.voice_turn_index = index
            matched.save(update_fields=["voice_conversation_id", "voice_turn_index", "updated_at"])
            stamped += 1
            continue

        sender = (
            _consumer_participant(session, consumer)
            if role == "user"
            else _agent_participant(session, consumer)
        )
        try:
            Message.objects.create(
                session=session,
                sender=sender,
                text=text,
                voice_conversation_id=conversation_id,
                voice_turn_index=index,
            )
        except IntegrityError:
            continue
        created += 1

    if created:
        session.updated_at = timezone.now()
        session.save(update_fields=["updated_at"])

    return {
        "status": "ok",
        "created": created,
        "stamped": stamped,
        "session_id": session.id,
        "grant_id": grant.id,
    }
