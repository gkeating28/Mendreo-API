from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from ..attribute.models import Attribute
from ..consumer.models import Consumer
from ..utils import Constants
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel


class KnowledgeField(SmartModel):
    """Admin-defined thing the platform wants to know about users."""

    id = CharIDField(primary_key=True, prefix="knf_")

    key = models.CharField(max_length=255, unique=True)
    label = models.CharField(max_length=255)
    category = models.CharField(max_length=255, blank=True, default="")
    value_type = EnumField(options=Constants.KNOWLEDGE_VALUE_TYPES, default=Constants.KNOWLEDGE_VALUE_TYPE_TEXT)
    sensitive = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"KnowledgeField: {self.key}"

    def get_permission_key(self):
        return "knowledge"


class KnowledgeQuestion(SmartModel):
    """Conversational prompt that populates a KnowledgeField."""

    id = CharIDField(primary_key=True, prefix="knq_")

    prompt = models.TextField()
    target_field = models.ForeignKey(
        KnowledgeField,
        related_name="questions",
        on_delete=models.CASCADE,
    )
    trigger = EnumField(
        options=Constants.KNOWLEDGE_TRIGGERS,
        default=Constants.KNOWLEDGE_TRIGGER_MANUAL_ONLY,
    )
    trigger_config = models.JSONField(default=dict, blank=True)
    suggested_responses = ArrayField(
        models.CharField(max_length=255, blank=False),
        blank=True,
        null=True,
    )
    extraction_prompt = models.TextField(blank=True, default="")
    flows = ArrayField(
        EnumField(options=Constants.KNOWLEDGE_FLOWS),
        blank=True,
        default=list,
    )
    # Per-variant order, e.g. {"initial": 1, "return": 3}. Falls back to `order`.
    order_by_flow = models.JSONField(default=dict, blank=True)

    response_type = EnumField(
        options=Constants.KNOWLEDGE_RESPONSE_TYPES,
        default=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
    )
    # Slider (0–10): two anchors + up to 11 value labels (empty string allowed).
    anchor_labels = ArrayField(
        models.CharField(max_length=64, blank=True),
        size=2,
        blank=True,
        null=True,
    )
    value_labels = ArrayField(
        models.CharField(max_length=64, blank=True),
        size=Constants.SLIDER_VALUE_LABEL_COUNT,
        blank=True,
        null=True,
    )
    # Multi-select constraints (null = unset / no constraint).
    min_selections = models.PositiveIntegerField(null=True, blank=True)
    max_selections = models.PositiveIntegerField(null=True, blank=True)

    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"KnowledgeQuestion: {self.id}"

    def get_permission_key(self):
        return "knowledge"

    def order_for_flow(self, flow: str) -> int:
        mapping = self.order_by_flow or {}
        if flow in mapping and mapping[flow] is not None:
            try:
                return int(mapping[flow])
            except (TypeError, ValueError):
                pass
        return self.order


class KnowledgeEntry(SmartModel):
    """
    A single piece of knowledge about one user for one field.

    Append-only history: the current value is the most recent non-deleted entry
    for (consumer, field).
    """

    id = CharIDField(primary_key=True, prefix="kne_")

    consumer = models.ForeignKey(Consumer, related_name="knowledge_entries", on_delete=models.CASCADE)
    field = models.ForeignKey(KnowledgeField, related_name="entries", on_delete=models.CASCADE)
    value = models.TextField()
    source = EnumField(options=Constants.KNOWLEDGE_ENTRY_SOURCES)
    confidence = models.FloatField(default=1.0)

    knowledge_question = models.ForeignKey(
        KnowledgeQuestion,
        related_name="entries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    session = models.ForeignKey(
        "api.Session",
        related_name="knowledge_entries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    attribute = models.ForeignKey(
        Attribute,
        related_name="knowledge_entries",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_by = models.ForeignKey(
        "api.User",
        related_name="knowledge_entries_created",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        indexes = [
            models.Index(fields=["consumer", "field", "-created_at"]),
            models.Index(fields=["consumer", "-created_at"]),
            models.Index(fields=["source"]),
        ]

    def __str__(self):
        return f"KnowledgeEntry: {self.id}"

    def get_permission_key(self):
        return "knowledge"

    @staticmethod
    def current_for(consumer, field):
        return (
            KnowledgeEntry.objects.filter(consumer=consumer, field=field)
            .order_by("-created_at")
            .first()
        )
