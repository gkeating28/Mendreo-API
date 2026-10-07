from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField

from ..utils import Constants
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel
from .constants import EMBEDDING_DIMENSIONS


class KnowledgeSource(SmartModel):
    """Approved clinical material. Never user knowledge or a transcript."""

    id = CharIDField(primary_key=True, prefix="ksrc_")

    title = models.CharField(max_length=255)
    kind = EnumField(options=Constants.KNOWLEDGE_SOURCE_KINDS)
    status = EnumField(
        options=Constants.KNOWLEDGE_SOURCE_STATUSES,
        default=Constants.KNOWLEDGE_SOURCE_STATUS_DRAFT,
    )
    version = models.PositiveIntegerField(default=1)
    index_status = models.CharField(max_length=16, default="idle")
    index_error = models.TextField(blank=True, default="")

    file = models.ForeignKey(
        "api.File",
        related_name="knowledge_sources",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    post = models.ForeignKey(
        "api.Post",
        related_name="knowledge_sources",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    body = models.TextField(null=True, blank=True)
    licence_note = models.TextField(blank=True, default="")

    clinical_owner = models.ForeignKey(
        "api.Admin",
        related_name="knowledge_sources_owned",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    submitted_by = models.ForeignKey(
        "api.Admin",
        related_name="knowledge_sources_submitted",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "api.Admin",
        related_name="knowledge_sources_approved",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    exercise_ids = models.JSONField(default=list, blank=True)
    tags = models.ManyToManyField("api.Tag", related_name="knowledge_sources", blank=True)

    class Meta:
        indexes = [
            GinIndex(fields=["exercise_ids"], name="ksrc_exercise_ids_gin"),
        ]

    def __str__(self):
        return f"KnowledgeSource: {self.title}"

    def get_permission_key(self):
        return "knowledge_sources"

    def delete(self):
        super().delete()
        self.chunks.filter(active=True).update(active=False)


class KnowledgeChunk(SmartModel):
    id = CharIDField(primary_key=True, prefix="kchk_")

    source = models.ForeignKey(
        KnowledgeSource,
        related_name="chunks",
        on_delete=models.CASCADE,
    )
    source_version = models.PositiveIntegerField()
    ordinal = models.PositiveIntegerField()
    heading_path = models.TextField(blank=True, default="")
    text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS)
    search_vector = models.GeneratedField(
        expression=SearchVector("text", config="english"),
        output_field=SearchVectorField(),
        db_persist=True,
    )
    active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["source", "active"], name="kchunk_source_active_idx"),
            GinIndex(fields=["search_vector"], name="kchunk_search_gin"),
            HnswIndex(
                name="kchunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"KnowledgeChunk: {self.id}"
