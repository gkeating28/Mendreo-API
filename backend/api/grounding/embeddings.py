"""Embed clinical text. Tests inject a fake embedder and never call Google."""

from __future__ import annotations

import logging
import math
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


def _embed_with_retry(texts: list[str]) -> list[list[float]]:
    last: Exception | None = None
    for attempt in range(3):
        try:
            return _google_embed(texts)
        except Exception as exc:
            if _quota_exhausted(exc):
                raise RuntimeError(
                    "Google's embedding quota is used up. In Google AI Studio, "
                    "enable billing for this API key, then publish the source again."
                ) from exc
            last = exc
            logger.warning("embedding attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.25 * (attempt + 1))
    assert last is not None
    raise last


def _quota_exhausted(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def _google_embed(texts: list[str]) -> list[list[float]]:
    from google.genai import types

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
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
        )
        embeddings = list(response.embeddings or [])
        if len(embeddings) != len(batch):
            raise RuntimeError("embedding batch size mismatch")
        for item in embeddings:
            vectors.append(list(item.values))
    return vectors


def _embed_client():
    """Use a decryptable provider key, or the GOOGLE_API_KEY on this process."""
    from ..utils import Constants
    from ..utils.AiProviderFactory import build_google_genai_client, ensure_providers_ready

    candidates = [
        provider
        for provider in ensure_providers_ready()
        if provider.provider == Constants.AI_PROVIDER_GOOGLE
    ]
    if not candidates:
        raise RuntimeError("No enabled Google provider for embeddings")
    return build_google_genai_client(candidates[0])


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
