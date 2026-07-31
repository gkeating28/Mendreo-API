"""Build pydantic-ai / vendor clients from configured AiProvider rows."""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

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
from ..utils import Constants

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AiProviderError(Exception):
    """Raised when no usable AI provider is configured."""


def build_pydantic_model(provider: AiProvider, model_name: str | None = None):
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


def build_google_genai_client(provider: AiProvider) -> genai.Client:
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
    operation: Callable[[AiProvider], T],
    *,
    model_name: str | None = None,
    provider_type: str | None = None,
    prefer: AiProvider | None = None,
) -> tuple[T, AiProvider]:
    """
    Run ``operation(provider)`` against the default (or preferred) provider,
    then other enabled providers on failure.
    """
    candidates = list(
        AiProvider.iter_failover_candidates(prefer=prefer, provider_type=provider_type)
    )
    if not candidates:
        # One more attempt in case env keys were set after process start / first boot.
        AiProvider.seed_from_env_if_empty()
        candidates = list(
            AiProvider.iter_failover_candidates(prefer=prefer, provider_type=provider_type)
        )
    if not candidates:
        raise AiProviderError(
            "No enabled AI providers configured. "
            "Add one via POST /ai-providers or set GOOGLE_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY."
        )

    errors: list[str] = []
    for index, provider in enumerate(candidates):
        try:
            # Optional hint for operations that want the resolved model name
            provider._resolved_model_name = provider.resolve_model_name(model_name)  # noqa: SLF001
            result = operation(provider)
            if index > 0:
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


def get_default_or_raise() -> AiProvider:
    provider = AiProvider.get_default()
    if not provider:
        # Try any enabled after seed
        candidates = AiProvider.iter_failover_candidates()
        if candidates:
            return candidates[0]
        raise AiProviderError(
            "No enabled AI providers configured. "
            "Add one via POST /ai-providers or set GOOGLE_API_KEY."
        )
    return provider
