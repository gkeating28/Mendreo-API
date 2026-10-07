"""Hybrid search. Reciprocal rank fusion orders only; it is never a threshold."""

from __future__ import annotations

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import Q
from pgvector.django import CosineDistance

from ..setting.models import Setting
from ..utils import Constants
from .chunking import take_within_budget
from .constants import BELOW_THRESHOLD_LIMIT, CANDIDATE_LIMIT, RRF_K
from .embeddings import embed_texts
from .models import KnowledgeChunk


def search_chunks(query: str, exercise_id: str | None = None) -> tuple[list[dict], list[dict]]:
    text = (query or "").strip()
    if not text:
        return [], []
    vector = embed_texts([text])[0]
    scoped = _scoped(exercise_id)
    cosine_rows = list(
        scoped.annotate(distance=CosineDistance("embedding", vector))
        .order_by("distance", "id")[: CANDIDATE_LIMIT + BELOW_THRESHOLD_LIMIT]
    )
    cosine_list = cosine_rows[:CANDIDATE_LIMIT]
    search_query = SearchQuery(text, config="english")
    fts_rows = list(
        scoped.annotate(fts_rank=SearchRank("search_vector", search_query))
        .filter(fts_rank__gt=0)
        .order_by("-fts_rank", "id")[:CANDIDATE_LIMIT]
    )
    exercise_rows = []
    if exercise_id:
        exercise_rows = list(
            scoped.filter(source__exercise_ids__contains=[exercise_id])
            .annotate(distance=CosineDistance("embedding", vector))
            .order_by("distance", "id")[:CANDIDATE_LIMIT]
        )

    known = {row.id: row for row in cosine_rows}
    missing_ids = [
        row.id
        for row in list(fts_rows) + list(exercise_rows)
        if row.id not in known
    ]
    if missing_ids:
        for row in scoped.filter(id__in=missing_ids).annotate(
            distance=CosineDistance("embedding", vector)
        ):
            known[row.id] = row

    cosine_ranks = {row.id: index for index, row in enumerate(cosine_list, start=1)}
    fts_ranks = {row.id: index for index, row in enumerate(fts_rows, start=1)}
    exercise_ranks = {row.id: index for index, row in enumerate(exercise_rows, start=1)}

    ordered_ids: list[str] = []
    for row in list(cosine_list) + list(fts_rows) + list(exercise_rows):
        if row.id not in ordered_ids:
            ordered_ids.append(row.id)

    threshold = Setting.get_retrieval_min_similarity()
    kept: list[tuple] = []
    for chunk_id in ordered_ids:
        row = known.get(chunk_id)
        if row is None or not hasattr(row, "distance"):
            continue
        similarity = _similarity(row.distance)
        if similarity < threshold:
            continue
        kept.append((row, similarity, _rrf(chunk_id, cosine_ranks, fts_ranks, exercise_ranks)))
    kept.sort(key=lambda item: (-item[2], -item[1], item[0].id))

    max_chunks = Setting.get_retrieval_max_chunks()
    max_tokens = Setting.get_retrieval_max_tokens()
    chosen = take_within_budget(
        kept,
        max_chunks,
        max_tokens,
        lambda item: item[0].token_count,
    )
    selected_ids = {item[0].id for item in chosen}
    selected = [
        _payload(item[0], item[1], rank)
        for rank, item in enumerate(chosen, start=1)
    ]

    below = []
    misses = []
    for row in cosine_rows:
        if row.id in selected_ids:
            continue
        similarity = _similarity(row.distance)
        if similarity >= threshold:
            continue
        misses.append((row, similarity))
    misses.sort(key=lambda item: (-item[1], item[0].id))
    for row, similarity in misses[:BELOW_THRESHOLD_LIMIT]:
        below.append(_payload(row, similarity, None))
    return selected, below


def _scoped(exercise_id: str | None):
    queryset = KnowledgeChunk.objects.filter(
        active=True,
        source__status=Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED,
        source__deleted_at__isnull=True,
    ).select_related("source")
    if not exercise_id:
        return queryset
    return queryset.filter(
        Q(source__exercise_ids__contains=[exercise_id])
        | Q(
            source__kind__in=[
                Constants.KNOWLEDGE_SOURCE_KIND_UP_SOURCE,
                Constants.KNOWLEDGE_SOURCE_KIND_GUIDANCE,
            ]
        )
    )


def _similarity(distance) -> float:
    value = 1.0 - float(distance)
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return round(value, 6)


def _rrf(chunk_id, cosine_ranks, fts_ranks, exercise_ranks) -> float:
    score = 0.0
    for ranks in (cosine_ranks, fts_ranks, exercise_ranks):
        rank = ranks.get(chunk_id)
        if rank:
            score += 1.0 / (RRF_K + rank)
    return score


def _payload(row, similarity: float, rank: int | None) -> dict:
    source = row.source
    return {
        "chunk_id": row.id,
        "source_id": source.id,
        "title": source.title,
        "heading_path": row.heading_path or "",
        "text": row.text,
        "similarity": similarity,
        "rank": rank,
        "token_count": row.token_count,
    }
