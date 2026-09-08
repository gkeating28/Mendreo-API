"""Webhook HMAC — same contract as elevenlabs.webhooks.construct_event."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from rest_framework.exceptions import PermissionDenied

# Official SDK rejects signatures older than 30 minutes.
_MAX_AGE_SECONDS = 30 * 60


class ElevenLabsWebhookError(PermissionDenied):
    default_detail = "Invalid ElevenLabs webhook signature"


def construct_event(raw_body, sig_header: str | None, secret: str) -> dict:
    """
    Verify ElevenLabs-Signature and parse the JSON payload.

    Prefers the official SDK when installed:

        elevenlabs.webhooks.construct_event(rawBody=..., sig_header=..., secret=...)

    Falls back to the documented HMAC (t=<unix>,v0=<hex>) so tests and staging
    work without pinning the SDK.
    """
    if not secret:
        raise ElevenLabsWebhookError("ElevenLabs webhook secret is not configured")
    if not sig_header:
        raise ElevenLabsWebhookError("Missing ElevenLabs-Signature header")

    payload = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body

    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs.errors import BadRequestError

        client = ElevenLabs(api_key="webhook-verify")
        try:
            return client.webhooks.construct_event(
                rawBody=payload,
                sig_header=sig_header,
                secret=secret,
            )
        except TypeError:
            return client.webhooks.construct_event(payload, sig_header, secret)
        except BadRequestError as exc:
            raise ElevenLabsWebhookError(str(exc) or "Invalid signature") from exc
    except ImportError:
        pass

    return _hmac_construct_event(payload, sig_header, secret)


def _hmac_construct_event(payload: str, sig_header: str, secret: str) -> dict:
    timestamp = None
    signatures = []
    for item in sig_header.split(","):
        item = item.strip()
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key == "t":
            timestamp = value
        elif key == "v0":
            signatures.append(value)

    if not timestamp or not signatures:
        raise ElevenLabsWebhookError("Malformed ElevenLabs-Signature header")

    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise ElevenLabsWebhookError("Invalid signature timestamp") from exc

    if abs(time.time() - ts) > _MAX_AGE_SECONDS:
        raise ElevenLabsWebhookError("Expired webhook signature")

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not any(hmac.compare_digest(expected, sig) for sig in signatures):
        raise ElevenLabsWebhookError("Invalid webhook signature")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ElevenLabsWebhookError("Invalid webhook JSON") from exc
