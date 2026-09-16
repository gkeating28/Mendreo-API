"""ElevenLabs HTTP helpers (server-side only)."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ElevenLabsConfigError(Exception):
    pass


class ElevenLabsRequestError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _clean_secret(value) -> str:
    """Strip BOM, whitespace, and wrapping quotes from env-sourced secrets."""
    text = (value or "").replace("\ufeff", "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].replace("\ufeff", "").strip()
    return text


def _nonempty(value) -> bool:
    return bool(_clean_secret(value))


def _is_quoted(value) -> bool:
    text = (value or "").replace("\ufeff", "").strip()
    return len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}


def _agent_id_kind(agent_id: str) -> str:
    if not agent_id:
        return "missing"
    if agent_id.startswith("agent_"):
        return "agent"
    if agent_id.startswith("seng_"):
        return "seng"
    return "other"


def _api_key_kind(api_key: str) -> str:
    if not api_key:
        return "missing"
    if api_key.startswith("sk_"):
        return "sk"
    if api_key.startswith("key_"):
        return "key_id"
    return "other"


def _api_base_host() -> str:
    base = _clean_secret(getattr(settings, "ELEVENLABS_API_BASE", None) or "https://api.elevenlabs.io")
    return urlparse(base).netloc or base


def config_presence() -> dict:
    """Presence flags only — never return secret values.

    `settings_*` is what `/voice/token` uses (snapshotted at process import).
    `environ_*` is `os.environ` at request time. A mismatch means the process
    started before the vars were injected.

    Railway injects `RAILWAY_SERVICE_ID` / `RAILWAY_DEPLOYMENT_ID` on every
    service; include them so a live probe can be matched to the dashboard.

    `agent_id_kind` / `agent_id_length` diagnose 400s from ElevenLabs without
    exposing the id. Valid conversational agents start with `agent_` or `seng_`.
    `api_key_kind` is `sk` for secrets (`sk_…`); `key_id` means the dashboard
    key identifier was stored instead of the secret.
    """
    raw_settings_key = getattr(settings, "ELEVENLABS_API_KEY", None) or ""
    raw_environ_key = os.environ.get("ELEVENLABS_API_KEY") or ""
    settings_api_key = _nonempty(raw_settings_key)
    raw_settings_agent = getattr(settings, "ELEVENLABS_AGENT_ID", None) or ""
    raw_environ_agent = os.environ.get("ELEVENLABS_AGENT_ID") or ""
    agent_id = _clean_secret(raw_settings_agent)
    api_key = _clean_secret(raw_settings_key)
    return {
        "settings_api_key": settings_api_key,
        "settings_agent_id": _nonempty(raw_settings_agent),
        "environ_api_key": _nonempty(raw_environ_key),
        "environ_agent_id": _nonempty(raw_environ_agent),
        "configured": settings_api_key and _nonempty(raw_settings_agent),
        "railway_service_id": (os.environ.get("RAILWAY_SERVICE_ID") or "").strip(),
        "railway_deployment_id": (os.environ.get("RAILWAY_DEPLOYMENT_ID") or "").strip(),
        "agent_id_quoted": _is_quoted(raw_settings_agent) or _is_quoted(raw_environ_agent),
        "agent_id_kind": _agent_id_kind(agent_id),
        "agent_id_length": len(agent_id),
        "api_key_kind": _api_key_kind(api_key),
        "api_base_host": _api_base_host(),
    }


API_KEY_ID_MESSAGE = (
    "ELEVENLABS_API_KEY is a key ID, not the secret. "
    "Paste the sk_… value shown once when the key is created or rotated."
)


DEFAULT_VOICE_ID = "female_irish"
VOICE_LIBRARY_IDS = {
    "male_irish": "RlSVB64yXMZJjq67jbB1",
    "female_irish": "3b8fXc91YHS1i2DYAlBQ",
    "american_male": "TWutjvRaJqAX89preB4e",
    "american_female": "gJx1vCzNCD1EQHT212Ls",
    "british_female": "aj0fZfXTBc7E3By4X8L2",
    "british_male": "av1BMOR1GPgThz9p4fLo",
}
DEFAULT_TTS_MODEL_ID = "eleven_flash_v2_5"
TTS_OUTPUT_FORMAT = "mp3_44100_128"


def resolve_elevenlabs_voice(voice_id: str | None) -> tuple[str, str]:
    """Map a UserSettings.voice_id key to the ElevenLabs library ID."""
    key = voice_id if voice_id in VOICE_LIBRARY_IDS else DEFAULT_VOICE_ID
    return key, VOICE_LIBRARY_IDS[key]


def _require_api_key() -> str:
    api_key = _clean_secret(settings.ELEVENLABS_API_KEY)
    if not api_key:
        raise ElevenLabsConfigError("ElevenLabs is not configured (ELEVENLABS_API_KEY).")
    if not api_key.startswith("sk_"):
        raise ElevenLabsConfigError(API_KEY_ID_MESSAGE)
    return api_key


def _require_config():
    api_key = _require_api_key()
    agent_id = _clean_secret(settings.ELEVENLABS_AGENT_ID)
    if not agent_id:
        raise ElevenLabsConfigError(
            "ElevenLabs is not configured (ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID)."
        )
    return api_key, agent_id


def tts_model_id() -> str:
    return _clean_secret(getattr(settings, "ELEVENLABS_TTS_MODEL_ID", None)) or DEFAULT_TTS_MODEL_ID


def synthesize_speech(text: str, elevenlabs_voice_id: str) -> tuple[bytes, str]:
    """Standard ElevenLabs TTS (not Conversational AI). Returns (audio, content_type)."""
    api_key = _require_api_key()
    voice_id = _clean_secret(elevenlabs_voice_id)
    model_id = tts_model_id()
    base = _clean_secret(settings.ELEVENLABS_API_BASE or "https://api.elevenlabs.io").rstrip("/")

    try:
        response = requests.post(
            f"{base}/v1/text-to-speech/{voice_id}",
            params={"output_format": TTS_OUTPUT_FORMAT},
            headers={
                "xi-api-key": api_key,
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={"text": text, "model_id": model_id},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("ElevenLabs TTS request error: %s", exc)
        raise ElevenLabsRequestError("Could not generate speech.", status_code=502) from exc

    if not response.ok:
        logger.warning(
            "ElevenLabs TTS failed status=%s body=%s",
            response.status_code,
            response.text[:300],
        )
        raise ElevenLabsRequestError(
            "Could not generate speech. " + _elevenlabs_error_summary(response),
            status_code=502,
        )

    content_type = (response.headers.get("Content-Type") or "audio/mpeg").split(";")[0].strip()
    if not content_type.startswith("audio/"):
        content_type = "audio/mpeg"
    return response.content, content_type


def _elevenlabs_error_summary(response) -> str:
    """Short, non-secret reason from an ElevenLabs error body."""
    try:
        data = response.json()
    except ValueError:
        text = (getattr(response, "text", None) or "").strip()
        return f"{response.status_code} {text[:160]}".strip()

    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("code") or detail.get("status") or detail.get("type")
        param = detail.get("param")
        if msg and param:
            return f"{response.status_code} {msg} ({param})"
        if msg:
            return f"{response.status_code} {msg}"
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict):
            msg = first.get("msg") or first.get("message") or "validation_error"
            loc = first.get("loc")
            if loc:
                return f"{response.status_code} {msg} loc={loc}"
            return f"{response.status_code} {msg}"
        if isinstance(first, str) and first.strip():
            return f"{response.status_code} {first.strip()[:160]}"
    if isinstance(detail, str) and detail.strip():
        return f"{response.status_code} {detail.strip()[:160]}"
    return str(response.status_code)


def mint_conversation_credentials() -> dict:
    """
    Fetch a WebRTC conversation token and a signed WebSocket URL.

    Either value may be missing if that ElevenLabs endpoint fails; the client
    uses whichever connection type it supports.
    """
    api_key, agent_id = _require_config()
    base = _clean_secret(settings.ELEVENLABS_API_BASE or "https://api.elevenlabs.io").rstrip("/")
    headers = {"xi-api-key": api_key}

    signed_url = None
    conversation_token = None
    errors = []

    try:
        signed = requests.get(
            f"{base}/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers=headers,
            timeout=15,
        )
        if signed.ok:
            signed_url = (signed.json() or {}).get("signed_url")
        else:
            errors.append(f"signed-url {_elevenlabs_error_summary(signed)}")
            logger.warning(
                "ElevenLabs signed-url failed status=%s body=%s",
                signed.status_code,
                signed.text[:300],
            )
    except requests.RequestException as exc:
        errors.append(f"signed-url {exc}")
        logger.warning("ElevenLabs signed-url request error: %s", exc)

    try:
        token_resp = requests.get(
            f"{base}/v1/convai/conversation/token",
            params={"agent_id": agent_id},
            headers=headers,
            timeout=15,
        )
        if token_resp.ok:
            body = token_resp.json() or {}
            conversation_token = body.get("token") or body.get("conversation_token")
        else:
            errors.append(f"token {_elevenlabs_error_summary(token_resp)}")
            logger.warning(
                "ElevenLabs conversation token failed status=%s body=%s",
                token_resp.status_code,
                token_resp.text[:300],
            )
    except requests.RequestException as extra:
        errors.append(f"token {extra}")
        logger.warning("ElevenLabs conversation token request error: %s", extra)

    if not signed_url and not conversation_token:
        raise ElevenLabsRequestError(
            "Could not mint an ElevenLabs conversation credential. " + "; ".join(errors),
            status_code=502,
        )

    return {
        "signed_url": signed_url,
        "conversation_token": conversation_token,
    }
