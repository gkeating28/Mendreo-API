"""ElevenLabs HTTP helpers (server-side only)."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ElevenLabsConfigError(Exception):
    pass


class ElevenLabsRequestError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def _require_config():
    api_key = (settings.ELEVENLABS_API_KEY or "").strip()
    agent_id = (settings.ELEVENLABS_AGENT_ID or "").strip()
    if not api_key or not agent_id:
        raise ElevenLabsConfigError(
            "ElevenLabs is not configured (ELEVENLABS_API_KEY / ELEVENLABS_AGENT_ID)."
        )
    return api_key, agent_id


def mint_conversation_credentials() -> dict:
    """
    Fetch a WebRTC conversation token and a signed WebSocket URL.

    Either value may be missing if that ElevenLabs endpoint fails; the client
    uses whichever connection type it supports.
    """
    api_key, agent_id = _require_config()
    base = (settings.ELEVENLABS_API_BASE or "https://api.elevenlabs.io").rstrip("/")
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
            errors.append(f"signed-url {signed.status_code}")
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
            errors.append(f"token {token_resp.status_code}")
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
