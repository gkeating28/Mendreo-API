"""Embed clinical text. Tests inject a fake embedder and never call Google."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable

from .constants import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL

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
            last = exc
            logger.warning("embedding attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.25 * (attempt + 1))
    assert last is not None
    raise last


def _google_embed(texts: list[str]) -> list[list[float]]:
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
    client = build_google_genai_client(provider)
    vectors: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.models.embed_content(model=EMBEDDING_MODEL, contents=batch)
        embeddings = list(response.embeddings or [])
        if len(embeddings) != len(batch):
            raise RuntimeError("embedding batch size mismatch")
        for item in embeddings:
            vectors.append(list(item.values))
    return vectors


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]
