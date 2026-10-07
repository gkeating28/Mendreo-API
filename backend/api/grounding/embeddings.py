"""Embed clinical text. Tests inject a fake embedder and never call Google."""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable

from .constants import EMBED_TEXTS_PER_MINUTE, EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

Embedder = Callable[[list[str]], list[list[float]]]

_override: Embedder | None = None


def set_embedder(embedder: Embedder | None) -> None:
    global _override
    _override = embedder


def clear_embedder() -> None:
    set_embedder(None)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if _override is not None:
        raw = _override(list(texts))
    else:
        raw = _embed_with_retry(texts)
    if len(raw) != len(texts):
        raise RuntimeError("embedding count does not match input")
    vectors = []
    for vector in raw:
        values = [float(item) for item in list(vector)]
        if len(values) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"embedding dimension {len(values)} does not match {EMBEDDING_DIMENSIONS}"
            )
        vectors.append(_l2_normalize(values))
    return vectors


class EmbeddingRateLimit(RuntimeError):
    """A 429 from Google. Raised after the batch has already waited and retried."""


def _embed_with_retry(texts: list[str]) -> list[list[float]]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            return _google_embed(texts)
        except EmbeddingRateLimit:
            raise
        except Exception as exc:
            if _billing_quota(exc):
                raise
            last = exc
            logger.warning("embedding attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.25 * (attempt + 1))
    assert last is not None
    raise last


def _rate_limited(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def _billing_quota(exc: Exception) -> bool:
    text = str(exc).lower()
    return "billing" in text or "check your plan" in text


def _retry_delay(exc: Exception, attempt: int) -> float:
    match = re.search(r"retry in ([0-9.]+)\s*s", str(exc), re.IGNORECASE)
    if match:
        return min(float(match.group(1)) + 1, 120)
    return float(min(15 * (2**attempt), 60))


def _google_embed(texts: list[str]) -> list[list[float]]:
    client = _embed_client()
    vectors: list[list[float]] = []
    # Small batches. Gemini counts every text toward the per-minute quota,
    # so a whole guide sent at once returns 429.
    batch_size = 10
    interval = 60 / EMBED_TEXTS_PER_MINUTE
    for index, start in enumerate(range(0, len(texts), batch_size)):
        if index:
            time.sleep(batch_size * interval)
        batch = texts[start : start + batch_size]
        vectors.extend(_embed_batch(client, batch))
    return vectors


def _embed_batch(client, batch: list[str]) -> list[list[float]]:
    """Retry a per-minute 429. A billing-quota 429 is returned as Google wrote it."""
    from google.genai import types

    last: Exception | None = None
    for attempt in range(6):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=batch,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
            )
            embeddings = list(response.embeddings or [])
            if len(embeddings) != len(batch):
                raise RuntimeError("embedding batch size mismatch")
            return [list(item.values) for item in embeddings]
        except Exception as exc:
            last = exc
            if _billing_quota(exc) or not _rate_limited(exc):
                raise
            delay = _retry_delay(exc, attempt)
            logger.warning(
                "embedding rate limited (attempt %s), waiting %ss: %s",
                attempt + 1,
                delay,
                exc,
            )
            time.sleep(delay)
    assert last is not None
    detail = str(last).splitlines()[0][:300]
    raise EmbeddingRateLimit(f"Google is rate-limiting embeddings. {detail}") from last


def _embed_client():
    """Use the Google row in AI providers. Do not substitute GOOGLE_API_KEY."""
    from ..ai_provider.models import AiProvider
    from ..utils import Constants
    from ..utils.AiProviderFactory import build_google_genai_client

    provider = (
        AiProvider.objects.filter(provider=Constants.AI_PROVIDER_GOOGLE, enabled=True)
        .order_by("-is_default", "created_at")
        .first()
    )
    if provider is None:
        raise RuntimeError("No enabled Google provider for embeddings")
    try:
        provider.get_api_key()
    except Exception as exc:
        raise RuntimeError(
            "The Google key in AI providers could not be decrypted. "
            "Indexing has to run where AI_SECRETS_MASTER_KEY is set."
        ) from exc
    return build_google_genai_client(provider)


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
