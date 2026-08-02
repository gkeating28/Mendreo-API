"""Build pydantic-ai / vendor clients from configured AiProvider rows.

If the DB table is empty but env API keys exist, falls back to those keys so
the app keeps working (and retries seeding the DB when possible).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

from django.conf import settings
from google import genai
from google.genai import types
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from ..ai_provider.models import AiProvider, AiProviderAuditLog
from ..utils import Api, Constants

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AiProviderError(Exception):
    """Raised when no usable AI provider is configured."""


class ProviderLike(Protocol):
    id: str
    provider: str
    default_model: str
    enabled: bool
    is_default: bool

    def get_api_key(self) -> str: ...
    def resolve_model_name(self, requested_model: str | None) -> str: ...


@dataclass
class EnvBackedProvider:
    """In-memory provider when DB rows are missing but env keys are present."""

    id: str
    name: str
    provider: str
    default_model: str
    _api_key: str
    enabled: bool = True
    is_default: bool = True

    def get_api_key(self) -> str:
        return self._api_key

    def resolve_model_name(self, requested_model: str | None) -> str:
        if requested_model and AiProvider.model_belongs_to_provider(
            requested_model, self.provider
        ):
            return requested_model
        return self.default_model


def _provider_key_usable(provider: ProviderLike) -> bool:
    """Return True if the provider's API key can be decrypted / read."""
    try:
        key = provider.get_api_key()
        return bool(key and str(key).strip())
    except Exception as exc:  # noqa: BLE001 - decrypt / config errors are expected here
        logger.warning(
            "AI provider %s/%s API key unusable (%s)",
            getattr(provider, "id", "?"),
            getattr(provider, "provider", "?"),
            exc,
        )
        return False


def ensure_providers_ready() -> list[ProviderLike]:
    """
    Ensure we can serve AI traffic: seed DB from env when empty, prefer DB
    providers whose keys decrypt, otherwise fall back to env-backed providers.
    """
    try:
        seeded = AiProvider.seed_from_env_if_empty()
        if seeded:
            logger.info("AI providers seeded from environment into database")
    except Exception:
        logger.exception(
            "Failed to seed AI providers into the database "
            "(check AI_SECRETS_MASTER_KEY and GOOGLE_API_KEY on the worker)"
        )

    candidates = [p for p in AiProvider.iter_failover_candidates() if _provider_key_usable(p)]
    if candidates:
        return candidates

    env_providers = _env_backed_providers()
    if env_providers:
        logger.warning(
            "No usable AiProvider DB rows (missing/empty table or undecryptable keys); "
            "using environment API keys directly. "
            "Set AI_SECRETS_MASTER_KEY on the worker and run "
            "`manage.py seed_ai_providers --refresh-from-env` to re-encrypt keys."
        )
    return env_providers


def _env_backed_providers() -> list[EnvBackedProvider]:
    providers: list[EnvBackedProvider] = []
    google_key = (os.environ.get("GOOGLE_API_KEY") or Api.GOOGLE_API_KEY or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    anthropic_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()

    if google_key:
        providers.append(
            EnvBackedProvider(
                id="env_google",
                name="Google Gemini (env)",
                provider=Constants.AI_PROVIDER_GOOGLE,
                default_model=Constants.AI_PROVIDER_DEFAULT_MODELS[
                    Constants.AI_PROVIDER_GOOGLE
                ],
                _api_key=google_key,
                is_default=True,
            )
        )
    if openai_key:
        providers.append(
            EnvBackedProvider(
                id="env_openai",
                name="OpenAI (env)",
                provider=Constants.AI_PROVIDER_OPENAI,
                default_model=Constants.AI_PROVIDER_DEFAULT_MODELS[
                    Constants.AI_PROVIDER_OPENAI
                ],
                _api_key=openai_key,
                is_default=not bool(google_key),
            )
        )
    if anthropic_key:
        providers.append(
            EnvBackedProvider(
                id="env_anthropic",
                name="Anthropic (env)",
                provider=Constants.AI_PROVIDER_ANTHROPIC,
                default_model=Constants.AI_PROVIDER_DEFAULT_MODELS[
                    Constants.AI_PROVIDER_ANTHROPIC
                ],
                _api_key=anthropic_key,
                is_default=not bool(google_key or openai_key),
            )
        )
    return providers


def build_pydantic_model(provider: ProviderLike, model_name: str | None = None):
    """Return a pydantic-ai model instance for chat / structured generation."""
    resolved = provider.resolve_model_name(model_name)
    api_key = provider.get_api_key()

    if provider.provider == Constants.AI_PROVIDER_GOOGLE:
        genai_client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=settings.GEMINI_HTTP_TIMEOUT_MS),
        )
        thinking_config = _google_thinking_config(resolved)
        return GoogleModel(
            model_name=resolved,
            provider=GoogleProvider(client=genai_client),
        ), GoogleModelSettings(google_thinking_config=thinking_config)

    if provider.provider == Constants.AI_PROVIDER_OPENAI:
        return OpenAIModel(
            model_name=resolved,
            provider=OpenAIProvider(api_key=api_key),
        ), None

    if provider.provider == Constants.AI_PROVIDER_ANTHROPIC:
        return AnthropicModel(
            model_name=resolved,
            provider=AnthropicProvider(api_key=api_key),
        ), None

    raise AiProviderError(f"Unsupported AI provider type: {provider.provider}")


def build_google_genai_client(provider: ProviderLike) -> genai.Client:
    if provider.provider != Constants.AI_PROVIDER_GOOGLE:
        raise AiProviderError("Google genai client requires a google AiProvider")
    return genai.Client(
        api_key=provider.get_api_key(),
        http_options=types.HttpOptions(timeout=settings.GEMINI_HTTP_TIMEOUT_MS),
    )


def _google_thinking_config(model_name: str) -> dict:
    if model_name.startswith(("gemini-3", "gemini-4")):
        return {"thinking_level": "minimal"}
    return {"thinking_budget": 0, "include_thoughts": False}


def run_with_failover(
    operation: Callable[[ProviderLike], T],
    *,
    model_name: str | None = None,
    provider_type: str | None = None,
    prefer: ProviderLike | None = None,
) -> tuple[T, ProviderLike]:
    """
    Run ``operation(provider)`` against the default (or preferred) provider,
    then other enabled providers on failure.
    """
    candidates = ensure_providers_ready()
    if provider_type:
        candidates = [p for p in candidates if p.provider == provider_type]
    if prefer is not None:
        candidates = [p for p in candidates if p.id != prefer.id]
        candidates.insert(0, prefer)

    if not candidates:
        raise AiProviderError(
            "No enabled AI providers configured. "
            "Set GOOGLE_API_KEY (and AI_SECRETS_MASTER_KEY) on the worker, "
            "or POST /ai-providers."
        )

    errors: list[str] = []
    for index, provider in enumerate(candidates):
        try:
            provider._resolved_model_name = provider.resolve_model_name(model_name)  # noqa: SLF001
            result = operation(provider)
            if index > 0 and isinstance(provider, AiProvider):
                AiProviderAuditLog.log(
                    provider=provider,
                    action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
                    actor=None,
                    detail={
                        "failed_providers": [p.id for p in candidates[:index]],
                        "errors": errors,
                        "model_name": model_name,
                    },
                )
            return result, provider
        except Exception as exc:  # noqa: BLE001 - need to try next vendor
            msg = f"{provider.id}/{provider.provider}: {exc}"
            logger.warning("AI provider call failed (%s); trying failover if available", msg)
            errors.append(msg)
            continue

    raise AiProviderError(
        "All AI providers failed: " + " | ".join(errors)
    )


def get_google_provider_for_images() -> ProviderLike:
    ensure_providers_ready()
    db = AiProvider.get_google_for_images()
    if db:
        return db
    for provider in _env_backed_providers():
        if provider.provider == Constants.AI_PROVIDER_GOOGLE:
            return provider
    raise AiProviderError(
        "Image generation requires an enabled Google AI provider (Imagen). "
        "Set GOOGLE_API_KEY on the worker or POST a google /ai-providers row."
    )


def get_default_or_raise() -> ProviderLike:
    candidates = ensure_providers_ready()
    if not candidates:
        raise AiProviderError(
            "No enabled AI providers configured. "
            "Set GOOGLE_API_KEY (and AI_SECRETS_MASTER_KEY) on the worker, "
            "or POST /ai-providers."
        )
    for provider in candidates:
        if provider.is_default:
            return provider
    return candidates[0]
