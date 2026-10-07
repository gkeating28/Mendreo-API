"""Index a published source. Embeddings run outside the version-swap transaction."""

from __future__ import annotations

import logging

from django.db import transaction

from ..utils import Constants
from .chunking import chunk_markdown
from .embeddings import embed_texts
from .models import KnowledgeChunk, KnowledgeSource

logger = logging.getLogger(__name__)


def index_now(source_id: str) -> int:
    """Index before the response is sent, using the AI providers table key.

    Vercel cannot decrypt that key: it has no AI_SECRETS_MASTER_KEY, so a
    local embed would fall through to the GOOGLE_API_KEY env var. The worker
    can decrypt the Google provider row, so Vercel waits on that process.
    """
    from django.conf import settings

    worker = (getattr(settings, "AI_WORKER_URL", "") or "").rstrip("/")
    secret = getattr(settings, "INTERNAL_API_SECRET", "") or ""
    if getattr(settings, "DEPLOYMENT_TARGET", "") == "vercel" and worker and secret:
        import httpx

        response = httpx.post(
            f"{worker}/internal/knowledge/index",
            json={"source_id": source_id},
            headers={"X-Internal-Secret": secret},
            timeout=270,
        )
        response.raise_for_status()
        return int(response.json()["chunks"])
    return index_source(source_id)


def index_source(source_id: str) -> int:
    source = KnowledgeSource.objects.filter(id=source_id).first()
    if source is None or not _indexable(source):
        return 0
    text = read_source_text(source)
    if not text.strip():
        logger.info("knowledge source %s has no text; previous chunks stay active", source_id)
        return 0
    pieces = chunk_markdown(text)
    if not pieces:
        return 0
    vectors = embed_texts([piece.text for piece in pieces])
    with transaction.atomic():
        locked = KnowledgeSource.objects.select_for_update().get(id=source_id)
        if not _indexable(locked):
            return 0
        if read_source_text(locked) != text:
            logger.info("knowledge source %s changed during embedding; nothing written", source_id)
            return 0
        has_active = KnowledgeChunk.objects.filter(source=locked, active=True).exists()
        version = locked.version + 1 if has_active else locked.version
        KnowledgeChunk.objects.filter(source=locked, active=True).update(active=False)
        KnowledgeChunk.objects.bulk_create(
            [
                KnowledgeChunk(
                    source=locked,
                    source_version=version,
                    ordinal=index,
                    heading_path=piece.heading_path,
                    text=piece.text,
                    token_count=piece.token_count,
                    embedding=vectors[index],
                    active=True,
                )
                for index, piece in enumerate(pieces)
            ]
        )
        if locked.version != version:
            locked.version = version
            locked.save(update_fields=["version", "updated_at"])
    return len(pieces)


def read_source_text(source: KnowledgeSource) -> str:
    if source.kind == Constants.KNOWLEDGE_SOURCE_KIND_POST and source.post_id:
        post = source.post
        return (post.body or "") if post is not None else ""
    if (source.body or "").strip():
        return source.body or ""
    if source.file_id and source.file is not None:
        key = (source.file.url or "").lstrip("/")
        if not key:
            return ""
        from ..utils.File import download_text

        return download_text(source.file.url) or ""
    return ""


def duplicates_reference_material(text: str) -> bool:
    """exercise_reference must not be a copy of an exercise or step note."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    from ..exercise.models import Exercise
    from ..step.models import Step

    for value in Exercise.objects.exclude(reference_material="").values_list(
        "reference_material", flat=True
    ):
        if (value or "").strip() == normalized:
            return True
    for value in Step.objects.exclude(reference_material="").values_list(
        "reference_material", flat=True
    ):
        if (value or "").strip() == normalized:
            return True
    return False


def _indexable(source: KnowledgeSource) -> bool:
    if source.deleted_at is not None:
        return False
    if source.status != Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED:
        return False
    if source.kind == Constants.KNOWLEDGE_SOURCE_KIND_UP_SOURCE and not (
        source.licence_note or ""
    ).strip():
        logger.warning("up_source %s refused: licence_note is empty", source.id)
        return False
    if source.kind == Constants.KNOWLEDGE_SOURCE_KIND_EXERCISE_REFERENCE:
        if duplicates_reference_material(read_source_text(source)):
            logger.warning(
                "exercise_reference %s refused: text copies reference_material",
                source.id,
            )
            return False
    return True
