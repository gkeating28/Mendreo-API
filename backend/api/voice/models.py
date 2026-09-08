from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from ..consumer.models import Consumer
from ..session.models import Session
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel

TOKEN_BYTES = 32
HASH_HEX_LENGTH = 64


def hash_grant_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_grant_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class VoiceGrant(SmartModel):
    """
    Short-lived binding from an ElevenLabs voice conversation to one consumer session.

    The client receives the raw token (as custom_llm_extra_body.grant). We only store
    token_hash. Identity for Custom LLM callbacks is this grant — never a client user_id.
    """

    id = CharIDField(primary_key=True, prefix="vgr_")

    consumer = models.ForeignKey(
        Consumer,
        related_name="voice_grants",
        on_delete=models.CASCADE,
    )
    session = models.ForeignKey(
        Session,
        related_name="voice_grants",
        on_delete=models.CASCADE,
    )
    token_hash = models.CharField(max_length=HASH_HEX_LENGTH, unique=True)
    expires_at = models.DateTimeField()
    elevenlabs_conversation_id = models.CharField(max_length=64, null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["consumer", "-created_at"], name="api_vgr_consumer_created_idx"),
            models.Index(fields=["elevenlabs_conversation_id"], name="api_vgr_elevenlabs_idx"),
            models.Index(fields=["expires_at"], name="api_vgr_expires_idx"),
        ]

    def __str__(self):
        return f"VoiceGrant: {self.id}"

    def get_permission_key(self):
        return "sessions"

    @property
    def is_usable(self) -> bool:
        if self.revoked_at is not None:
            return False
        return timezone.now() < self.expires_at

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at", "updated_at"])

    @classmethod
    def issue(cls, *, consumer, session, ttl=None) -> tuple["VoiceGrant", str]:
        ttl = ttl if ttl is not None else timedelta(
            hours=getattr(settings, "ELEVENLABS_GRANT_TTL_HOURS", 4)
        )
        raw = generate_grant_token()
        grant = cls.objects.create(
            consumer=consumer,
            session=session,
            token_hash=hash_grant_token(raw),
            expires_at=timezone.now() + ttl,
        )
        return grant, raw

    @classmethod
    def resolve(cls, raw_token: str | None) -> "VoiceGrant | None":
        if not raw_token or not isinstance(raw_token, str):
            return None
        token = raw_token.strip()
        if not token:
            return None
        digest = hash_grant_token(token)
        grant = cls.objects.select_related("consumer", "session", "consumer__user").filter(
            token_hash=digest
        ).first()
        if grant is None:
            # Constant-time dummy compare so missing grants aren't obviously faster.
            hmac.compare_digest(digest, digest)
            return None
        if not grant.is_usable:
            return None
        return grant
