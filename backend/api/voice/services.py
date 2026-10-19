"""Voice session minting, Custom LLM adapter, and post-call reconcile."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Iterable

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.db.utils import IntegrityError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..agent.models import Agent
from ..message.models import Message
from ..participant.models import Participant
from ..session.models import Session
from ..user.models import UserSettings
from ..utils.ExerciseOffer import (
    maybe_handle_offer_response,
    pending_offer_message,
    spoken_offer_chip,
    unresolved_offer_message,
)
from ..utils.MessageFlow import apply_agent_response
from .elevenlabs_client import (
    mint_conversation_credentials,
    resolve_elevenlabs_voice,
    synthesize_speech,
)
from .models import VoiceGrant, hash_grant_token

logger = logging.getLogger(__name__)

GENERAL_CHAT_ONLY = "Voice is only available for general chat."
TTS_USER_MESSAGE = "Only Toni's messages can be read aloud."
TTS_EMPTY_TEXT = "This message has no speakable text."
TTS_MAX_CHARS = 5000
VOICE_PREVIEW_TEXT = "Hi, I'm Toni. How are you feeling today?"
VOICE_DUPLICATE_WINDOW = timedelta(seconds=20)
# ElevenLabs retries a turn with a corrected transcript ("kinda" / "kind of").
# 0.85 keeps that pair and rejects a genuinely different sentence.
# A longer utterance is a continuation, not a retry, even below this line.
VOICE_RETRY_SIMILARITY = 0.85
# A corrected transcript can arrive while the first Gemini call is still running.
# Poll for its saved reply, and send a content token before cascade timeout (~8s).
VOICE_RETRY_POLL_SECONDS = 0.2
VOICE_RETRY_WAIT_SECONDS = 25
VOICE_RETRY_KEEPALIVE_SECONDS = 6
# Official Custom LLM buffer words (docs: "Let me think about that... ").
# "... " alone is not enough for ElevenLabs to treat TTFT as satisfied, and a
# tiny first chunk is often held in Railway/Gunicorn buffers until Gemini
# finishes — which is after cascade_timeout_seconds (default 8s).
ELEVENLABS_KEEPALIVE = "Let me think about that... "
SSE_FLUSH_PAD_CHARS = 8192
UNDERSTANDING_FALLBACK = (
    "Sorry, I had an issue understanding your message, can you repeat it or rephrase it for me please?"
)
_HAS_SPEECH_RE = re.compile(r"[A-Za-z0-9]")


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


def speakable_message_text(text: str | None) -> str:
    cleaned = (text or "").strip()
    if not cleaned or not _HAS_SPEECH_RE.search(cleaned):
        return ""
    if len(cleaned) > TTS_MAX_CHARS:
        return cleaned[:TTS_MAX_CHARS]
    return cleaned


def _resolve_tts_voice(consumer, voice_id: str | None = None) -> str:
    requested = (voice_id or "").strip() or None
    if requested:
        if requested not in UserSettings.VoiceId.values:
            raise ValidationError(
                {
                    "voice_id": "Must be one of: "
                    + ", ".join(UserSettings.VoiceId.values),
                },
            )
        _, elevenlabs_voice_id = resolve_elevenlabs_voice(requested)
        return elevenlabs_voice_id
    _, elevenlabs_voice_id = _consumer_voice(consumer)
    return elevenlabs_voice_id


def synthesize_spoken_text(
    consumer,
    text: str | None,
    voice_id: str | None = None,
) -> tuple[bytes, str]:
    """TTS for unsaved copy (practice demo). Same ElevenLabs library as message play."""
    spoken = speakable_message_text(text if isinstance(text, str) else "")
    if not spoken:
        raise ValidationError({"detail": TTS_EMPTY_TEXT})
    return synthesize_speech(spoken, _resolve_tts_voice(consumer, voice_id))


def synthesize_agent_message(consumer, message_id: str | None) -> tuple[bytes, str]:
    """TTS for one agent message the consumer already owns. Not live Talk."""
    if not message_id:
        raise ValidationError({"message_id": "This field is required."})

    message = (
        Message.objects.select_related("session", "sender")
        .filter(id=message_id, session__consumer=consumer)
        .first()
    )
    if message is None:
        raise ValidationError({"message_id": "Message not found."})
    if message.sender.agent_id is None:
        raise ValidationError({"detail": TTS_USER_MESSAGE})

    text = speakable_message_text(message.text)
    if not text:
        raise ValidationError({"detail": TTS_EMPTY_TEXT})

    return synthesize_speech(text, _resolve_tts_voice(consumer))


def synthesize_voice_preview(consumer, voice_id: str | None = None) -> tuple[bytes, str]:
    """Sample line for a voice option. Does not write UserSettings."""
    return synthesize_speech(VOICE_PREVIEW_TEXT, _resolve_tts_voice(consumer, voice_id))


def mint_voice_token(consumer, session_id: str | None = None) -> dict:
    session = resolve_general_session(consumer, session_id)
    credentials = mint_conversation_credentials()
    grant, raw_token = VoiceGrant.issue(consumer=consumer, session=session)
    voice_id, elevenlabs_voice_id = _consumer_voice(consumer)
    return {
        "conversation_token": credentials.get("conversation_token"),
        "signed_url": credentials.get("signed_url"),
        "session_id": session.id,
        "expires_at": grant.expires_at,
        "custom_llm_extra_body": {"grant": raw_token},
        "voice_id": voice_id,
        "elevenlabs_voice_id": elevenlabs_voice_id,
    }


def _consumer_voice(consumer) -> tuple[str, str]:
    prefs = UserSettings.for_user(consumer.user)
    return resolve_elevenlabs_voice(prefs.voice_id)


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


def _saved_text_matches(user_message: Message, source_text: str) -> bool:
    """True when the stored user row still says what this call started with."""
    user_message.refresh_from_db(fields=["text"])
    return _normalize_voice_text(user_message.text or "") == source_text


def _count_followup_agent_reply(user_message: Message, agent_message: Message) -> None:
    """Count another Toni line when this user row was already paired with a reply."""
    session = user_message.session
    with transaction.atomic():
        stored_last_at = (
            type(session).objects.filter(pk=session.pk)
            .values_list("last_message__created_at", flat=True)
            .first()
        )
        update_fields = ["messages_no", "agent_messages_no", "updated_at"]
        if stored_last_at is None or (
            agent_message.created_at and agent_message.created_at >= stored_last_at
        ):
            session.last_message = agent_message
            update_fields.append("last_message")
        session.messages_no = F("messages_no") + 1
        session.agent_messages_no = F("agent_messages_no") + 1
        session.save(update_fields=update_fields)


def _generate_agent_reply(grant: VoiceGrant, user_message: Message) -> Message | None:
    """Gemini for an existing user row. Does not insert another user message.

    Returns None when a continuation rewrote the user text while this call was
    in flight. The model reply is dropped so it is neither kept nor spoken.
    """
    source_text = _normalize_voice_text(user_message.text or "")
    session = Session.objects.select_related("consumer", "consumer__agent").get(pk=grant.session_id)
    session.refresh_from_db(fields=["cached_prompt"])
    agent_message = Agent.get_response(session=session, user_message=user_message)
    with transaction.atomic():
        locked = Message.objects.select_for_update().get(pk=user_message.pk)
        if _normalize_voice_text(locked.text or "") != source_text:
            logger.info(
                "dropping voice reply for superseded text grant=%s message=%s",
                grant.id,
                user_message.id,
            )
            agent_message.delete()
            return None
        already_replied = (
            Message.objects.filter(
                session=grant.session,
                sender__agent=grant.consumer.agent,
                created_at__gte=locked.created_at,
            )
            .exclude(pk=agent_message.pk)
            .exists()
        )
        if already_replied:
            _count_followup_agent_reply(locked, agent_message)
        else:
            apply_agent_response(locked, agent_message)
    return stamp_agent_voice_fields(agent_message, grant)


def run_toni_reply(grant: VoiceGrant, user_text: str) -> Message | None:
    """
    Same Gemini path as text chat: Agent.get_response + apply_agent_response.

    Neither helper reads the HTTP request or JWT — they only need Session + Message.
    Do not call POST /messages (that would enqueue/double-fire Gemini).
    """
    user_message = create_user_voice_message(grant=grant, text=user_text)
    return _generate_agent_reply(grant, user_message)


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


def sse_flush_padding(*, chunk_id: str, created: int, model: str) -> bytes:
    """Second SSE chunk large enough to push the filler through proxy buffers.

    Empty content so TTS does not speak the padding. Extra key is ignored by
    OpenAI-compatible clients; ElevenLabs reads choices[].delta.content.
    """
    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": ""},
                "finish_reason": None,
            }
        ],
        "flush_padding": " " * SSE_FLUSH_PAD_CHARS,
    }
    return f"data: {json.dumps(payload)}\n\n".encode("utf-8")


def iter_silent_completion_sse() -> Iterable[bytes]:
    """Acknowledge a non-turn (silence / duplicate) without calling Gemini."""
    created = int(time.time())
    chunk_id = "chatcmpl-silent"
    model = "mendreo-toni"
    yield sse_chunk(None, finish_reason="stop", chunk_id=chunk_id, created=created, model=model)
    yield b"data: [DONE]\n\n"


def _normalize_voice_text(text: str) -> str:
    cleaned = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _voice_texts_similar(left: str, right: str) -> bool:
    """True when two transcripts are the same turn after ASR correction."""
    a = _normalize_voice_text(left)
    b = _normalize_voice_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= VOICE_RETRY_SIMILARITY


def _voice_text_extends(earlier: str, later: str) -> bool:
    """True when later keeps the earlier words and adds more.

    A prefix ("I'm doing good" -> "... I had a good weekend") or an insertion
    ("I'm doing good" -> "I'm doing really good"). Replacing a word
    ("kinda" -> "kind of") is a correction, not a continuation.
    """
    old_words = _normalize_voice_text(earlier).split()
    new_words = _normalize_voice_text(later).split()
    if not old_words or len(new_words) <= len(old_words):
        return False
    for tag, _i1, _i2, _j1, _j2 in SequenceMatcher(None, old_words, new_words).get_opcodes():
        if tag in ("equal", "insert"):
            continue
        return False
    return True


def _recent_voice_user_message(grant: VoiceGrant):
    """Latest user voice row in this conversation, if it is still inside the retry window."""
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
        return None
    if last.created_at < timezone.now() - VOICE_DUPLICATE_WINDOW:
        return None
    return last


def _agent_reply_after(grant: VoiceGrant, user_message: Message) -> str:
    agent = (
        Message.objects.filter(
            session=grant.session,
            sender__agent=grant.consumer.agent,
            created_at__gte=user_message.created_at,
        )
        .order_by("created_at")
        .first()
    )
    return (agent.text or "").strip() if agent else ""


def _same_turn_retry(user_text: str, last_user: Message) -> bool:
    """A second completion whose transcript is the same utterance, lightly edited.

    ElevenLabs sends a corrected transcript as a new request ("kinda" / "kind of").
    Only that near-identical text is a retry. A longer utterance is a continuation,
    and a different sentence is a new turn, including when Toni has not replied yet.
    """
    return _voice_texts_similar(last_user.text or "", user_text)


def _continue_spoken_turn(grant: VoiceGrant, last_user: Message, user_text: str):
    """Rewrite the open user row and answer the full utterance once."""
    last_user.text = user_text
    last_user.save(update_fields=["text", "updated_at"])
    agent_message = _generate_agent_reply(grant, last_user)
    if agent_message is None:
        return "silent", ""
    return "speak", (agent_message.text or "").strip()


def _prepare_spoken_turn(grant: VoiceGrant, user_text: str):
    """Decide what this completion should speak.

    Returns ``("speak", text)``, ``("silent", "")`` when there is nothing to
    say, or ``("wait", user_message)`` when this is a retry and Toni's reply
    is not saved yet.
    """
    offer_result = try_voice_offer_reply(grant, user_text)
    if offer_result is not None:
        if getattr(offer_result.sender, "agent_id", None):
            return "speak", (offer_result.text or "").strip()
        return "silent", ""

    last_user = _recent_voice_user_message(grant)
    if last_user is not None and _voice_text_extends(last_user.text or "", user_text):
        return _continue_spoken_turn(grant, last_user, user_text)

    if last_user is not None and _same_turn_retry(user_text, last_user):
        reply = _agent_reply_after(grant, last_user)
        if reply:
            return "speak", reply
        return "wait", last_user

    agent_message = run_toni_reply(grant, user_text)
    if agent_message is None:
        return "silent", ""
    return "speak", (agent_message.text or "").strip()


def _iter_wait_for_reply(grant, user_message, *, chunk_id, created, model, source_text):
    """Poll for the in-flight reply, yielding keepalive chunks so the stream stays open.

    The return value is the saved reply, or "" when the wait expires or the
    user text is no longer the utterance this retry is waiting on.
    """
    deadline = time.monotonic() + VOICE_RETRY_WAIT_SECONDS
    next_keepalive = time.monotonic() + VOICE_RETRY_KEEPALIVE_SECONDS
    while True:
        if not _saved_text_matches(user_message, source_text):
            return ""
        reply = _agent_reply_after(grant, user_message)
        if reply:
            return reply
        now = time.monotonic()
        if now >= deadline:
            return ""
        if now >= next_keepalive:
            yield sse_chunk(
                spoken_llm_keepalive(),
                finish_reason=None,
                chunk_id=chunk_id,
                created=created,
                model=model,
            )
            next_keepalive = now + VOICE_RETRY_KEEPALIVE_SECONDS
        yield sse_flush_padding(chunk_id=chunk_id, created=created, model=model)
        time.sleep(min(VOICE_RETRY_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def _speak_after_retry_wait(grant, user_message, *, chunk_id, created, model):
    """Wait for the first call, then speak its reply. One Gemini call if it never arrives."""
    source_text = _normalize_voice_text(user_message.text or "")
    spoken = yield from _iter_wait_for_reply(
        grant,
        user_message,
        chunk_id=chunk_id,
        created=created,
        model=model,
        source_text=source_text,
    )
    if not _saved_text_matches(user_message, source_text):
        return ""
    if spoken:
        return spoken
    spoken = _agent_reply_after(grant, user_message)
    if spoken:
        return spoken
    generated = _generate_agent_reply(grant, user_message)
    if generated is None:
        return ""
    return (generated.text or "").strip() or UNDERSTANDING_FALLBACK


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
    """Filler + flush, then the spoken reply. No background work.

    A near-identical retry that arrives while Gemini is still running keeps
    this stream alive (padding, and the filler again before the cascade
    window) until the first call saves Toni's reply. A longer continuation
    answers the full text instead, and the first call drops its reply if the
    user row changed. A daemon thread + cache lock caused earlier regressions,
    so the wait stays on this request.
    """
    created = int(time.time())
    chunk_id = f"chatcmpl-{grant.id}"
    model = "mendreo-toni"

    def _chunk(content: str | None, finish_reason=None) -> bytes:
        return sse_chunk(
            content,
            finish_reason=finish_reason,
            chunk_id=chunk_id,
            created=created,
            model=model,
        )

    try:
        yield _chunk(spoken_llm_keepalive())
        yield sse_flush_padding(chunk_id=chunk_id, created=created, model=model)
        kind, payload = _prepare_spoken_turn(grant, user_text)
        if kind == "wait":
            spoken = yield from _speak_after_retry_wait(
                grant,
                payload,
                chunk_id=chunk_id,
                created=created,
                model=model,
            )
        elif kind == "silent":
            spoken = ""
        else:
            spoken = payload or UNDERSTANDING_FALLBACK
        if spoken:
            yield _chunk(spoken)
        yield _chunk(None, finish_reason="stop")
        yield b"data: [DONE]\n\n"
    except Exception:
        logger.exception(
            "Custom LLM Gemini path failed grant=%s session=%s",
            grant.id,
            grant.session_id,
        )
        yield _chunk(UNDERSTANDING_FALLBACK)
        yield _chunk(None, finish_reason="stop")
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
