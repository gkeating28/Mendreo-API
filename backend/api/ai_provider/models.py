from __future__ import annotations

import logging
import os

from django.db import models, transaction

from ..utils import Constants
from ..utils.AiSecrets import decrypt_api_key, encrypt_api_key, mask_api_key
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel

logger = logging.getLogger(__name__)


class AiProvider(SmartModel):
    """Admin-configured AI vendor credential + default model."""

    id = CharIDField(primary_key=True, prefix="aip_")

    name = models.CharField(max_length=255)
    provider = EnumField(options=Constants.AI_PROVIDERS)
    default_model = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)

    # Fernet ciphertext; never expose via API
    api_key_encrypted = models.TextField()

    extra_config = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "enabled"]),
        ]

    def __str__(self):
        return f"AiProvider: {self.id} ({self.provider})"

    def get_api_key(self) -> str:
        return decrypt_api_key(self.api_key_encrypted)

    def set_api_key(self, plaintext: str) -> None:
        self.api_key_encrypted = encrypt_api_key(plaintext)

    def api_key_last4(self) -> str | None:
        try:
            return mask_api_key(self.get_api_key())
        except Exception:
            return None

    def has_api_key(self) -> bool:
        return bool(self.api_key_encrypted)

    @staticmethod
    def model_belongs_to_provider(model_name: str, provider_type: str) -> bool:
        if not model_name:
            return False
        if model_name in Constants.AI_PROVIDER_SUGGESTED_MODELS.get(provider_type, []):
            return True
        prefixes = Constants.AI_PROVIDER_MODEL_PREFIXES.get(provider_type, ())
        return model_name.startswith(prefixes)

    def resolve_model_name(self, requested_model: str | None) -> str:
        if requested_model and self.model_belongs_to_provider(requested_model, self.provider):
            return requested_model
        return self.default_model

    @classmethod
    def get_default(cls) -> AiProvider | None:
        cls.seed_from_env_if_empty()
        return (
            cls.objects.filter(is_default=True, enabled=True)
            .order_by("created_at")
            .first()
        )

    @classmethod
    def iter_failover_candidates(cls, *, prefer: AiProvider | None = None, provider_type: str | None = None):
        """Yield enabled providers: preferred/default first, then others by created_at."""
        cls.seed_from_env_if_empty()
        query = cls.objects.filter(enabled=True)
        if provider_type:
            query = query.filter(provider=provider_type)

        providers = list(query.order_by("-is_default", "created_at"))
        if prefer and prefer in providers:
            providers.remove(prefer)
            providers.insert(0, prefer)
        return providers

    @classmethod
    def get_google_for_images(cls) -> AiProvider | None:
        """Prefer default if Google; else first enabled Google provider."""
        default = cls.get_default()
        if default and default.provider == Constants.AI_PROVIDER_GOOGLE and default.enabled:
            return default
        return (
            cls.objects.filter(provider=Constants.AI_PROVIDER_GOOGLE, enabled=True)
            .order_by("-is_default", "created_at")
            .first()
        )

    @classmethod
    def clear_default_flags(cls, *, except_id: str | None = None) -> None:
        query = cls.objects.filter(is_default=True)
        if except_id:
            query = query.exclude(id=except_id)
        query.update(is_default=False)

    @classmethod
    def promote_failover_default(cls, *, excluding_id: str | None = None, actor=None) -> AiProvider | None:
        """If no enabled default remains, promote the oldest other enabled provider."""
        has_default = cls.objects.filter(is_default=True, enabled=True)
        if excluding_id:
            has_default = has_default.exclude(id=excluding_id)
        if has_default.exists():
            return has_default.first()

        replacement = (
            cls.objects.filter(enabled=True)
            .exclude(id=excluding_id)
            .order_by("created_at")
            .first()
            if excluding_id
            else cls.objects.filter(enabled=True).order_by("created_at").first()
        )
        if not replacement:
            return None

        cls.clear_default_flags()
        replacement.is_default = True
        replacement.save(update_fields=["is_default", "updated_at"])
        AiProviderAuditLog.log(
            provider=replacement,
            action=Constants.AI_PROVIDER_AUDIT_SET_DEFAULT,
            actor=actor,
            detail={"reason": "auto_failover", "excluded_id": excluding_id},
        )
        return replacement

    def save(self, *args, **kwargs):
        making_default = self.is_default
        super().save(*args, **kwargs)
        if making_default:
            type(self).clear_default_flags(except_id=self.id)

    def delete(self):
        provider_id = self.id
        actor = getattr(self, "_audit_actor", None)
        was_default = self.is_default
        AiProviderAuditLog.log(
            provider=self,
            action=Constants.AI_PROVIDER_AUDIT_DELETED,
            actor=actor,
            detail={"was_default": was_default},
        )
        if was_default:
            self.is_default = False
            self.save(update_fields=["is_default", "updated_at"])
        super().delete()
        if was_default:
            type(self).promote_failover_default(excluding_id=provider_id, actor=actor)

    @classmethod
    @transaction.atomic
    def seed_from_env_if_empty(cls, *, allow_placeholder: bool = False) -> bool:
        """Create providers from env API keys when the table is empty. Returns True if seeded.

        If ``allow_placeholder`` is True and no env keys are present, seeds a Google
        placeholder so local/CI test setup still has a default provider row.
        """
        if cls.objects.filter(enabled=True).exists():
            return False

        from ..utils import Api

        seeds = []
        google_key = (
            os.environ.get("GOOGLE_API_KEY", "").strip()
            or (Api.GOOGLE_API_KEY or "").strip()
        )
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

        if google_key:
            seeds.append(
                (
                    "Google Gemini",
                    Constants.AI_PROVIDER_GOOGLE,
                    Constants.AI_PROVIDER_DEFAULT_MODELS[Constants.AI_PROVIDER_GOOGLE],
                    google_key,
                    True,
                    "env",
                )
            )
        if openai_key:
            seeds.append(
                (
                    "OpenAI",
                    Constants.AI_PROVIDER_OPENAI,
                    Constants.AI_PROVIDER_DEFAULT_MODELS[Constants.AI_PROVIDER_OPENAI],
                    openai_key,
                    not bool(google_key),
                    "env",
                )
            )
        if anthropic_key:
            seeds.append(
                (
                    "Anthropic",
                    Constants.AI_PROVIDER_ANTHROPIC,
                    Constants.AI_PROVIDER_DEFAULT_MODELS[Constants.AI_PROVIDER_ANTHROPIC],
                    anthropic_key,
                    not bool(google_key or openai_key),
                    "env",
                )
            )

        if not seeds and allow_placeholder:
            seeds.append(
                (
                    "Google Gemini",
                    Constants.AI_PROVIDER_GOOGLE,
                    Constants.AI_PROVIDER_DEFAULT_MODELS[Constants.AI_PROVIDER_GOOGLE],
                    "test-google-api-key",
                    True,
                    "placeholder",
                )
            )

        if not seeds:
            return False

        for name, provider_type, model, key, is_default, source in seeds:
            row = cls(
                name=name,
                provider=provider_type,
                default_model=model,
                is_default=is_default,
                enabled=True,
            )
            row.set_api_key(key)
            row.save()
            AiProviderAuditLog.log(
                provider=row,
                action=Constants.AI_PROVIDER_AUDIT_SEEDED,
                actor=None,
                detail={"source": source},
            )
            logger.info("Seeded AI provider %s (%s) from %s", name, provider_type, source)

        return True


class AiProviderAuditLog(SmartModel):
    """Immutable-ish audit trail for provider config and runtime failover."""

    id = CharIDField(primary_key=True, prefix="apal_")

    provider = models.ForeignKey(
        AiProvider,
        related_name="audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    provider_id_snapshot = models.CharField(max_length=40, db_index=True)
    provider_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    provider_type_snapshot = models.CharField(max_length=64, blank=True, default="")

    actor = models.ForeignKey(
        "api.User",
        related_name="ai_provider_audit_logs",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    action = EnumField(options=Constants.AI_PROVIDER_AUDIT_ACTIONS)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"AiProviderAuditLog: {self.id} ({self.action})"

    @classmethod
    def log(cls, *, provider: AiProvider | None, action: str, actor=None, detail: dict | None = None):
        provider_id = getattr(provider, "id", None) or (detail or {}).get("provider_id", "")
        return cls.objects.create(
            provider=provider if provider and getattr(provider, "pk", None) else None,
            provider_id_snapshot=str(provider_id or ""),
            provider_name_snapshot=getattr(provider, "name", "") or "",
            provider_type_snapshot=getattr(provider, "provider", "") or "",
            actor=actor,
            action=action,
            detail=detail or {},
        )
