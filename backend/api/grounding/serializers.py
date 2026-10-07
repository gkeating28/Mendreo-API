from django.utils import timezone
from rest_framework import serializers

from ..admin.models import Admin
from ..tag.models import Tag
from ..utils import Constants
from ..utils.Serializers import CreateModelSerializer, EditModelSerializer, ListModelSerializer
from .indexing import duplicates_reference_material
from .models import KnowledgeChunk, KnowledgeSource


class KnowledgeSourceCreateSerializer(CreateModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    exercise_ids = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )

    class Meta:
        model = KnowledgeSource
        fields = [
            "title",
            "kind",
            "file",
            "body",
            "licence_note",
            "clinical_owner",
            "exercise_ids",
            "tags",
        ]

    def validate_kind(self, value):
        if value not in Constants.KNOWLEDGE_SOURCE_KINDS:
            raise serializers.ValidationError("Unknown source kind.")
        return value

    def validate_clinical_owner(self, admin):
        if admin is not None and not isinstance(admin, Admin):
            raise serializers.ValidationError("clinical_owner must be an admin.")
        return admin


class KnowledgeSourceEditSerializer(EditModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        queryset=Tag.objects.all(), many=True, required=False
    )
    exercise_ids = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False
    )
    status = serializers.ChoiceField(
        choices=Constants.KNOWLEDGE_SOURCE_STATUSES, required=False
    )

    class Meta:
        model = KnowledgeSource
        fields = [
            "title",
            "kind",
            "file",
            "body",
            "licence_note",
            "clinical_owner",
            "exercise_ids",
            "tags",
            "status",
        ]

    def validate_status(self, value):
        if value == Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED:
            raise serializers.ValidationError("Publish a source with the approve action.")
        if value == Constants.KNOWLEDGE_SOURCE_STATUS_IN_REVIEW:
            raise serializers.ValidationError("Submit a source with the submit action.")
        return value


class KnowledgeSourceListSerializer(ListModelSerializer):
    class Meta:
        model = KnowledgeSource
        fields = [
            "id",
            "title",
            "kind",
            "status",
            "version",
            "licence_note",
            "clinical_owner",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "exercise_ids",
            "post",
            "file",
            "created_at",
            "updated_at",
        ]


class KnowledgeSourceDetailSerializer(KnowledgeSourceListSerializer):
    tags = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta(KnowledgeSourceListSerializer.Meta):
        fields = KnowledgeSourceListSerializer.Meta.fields + ["body", "tags"]


class KnowledgeChunkListSerializer(ListModelSerializer):
    class Meta:
        model = KnowledgeChunk
        fields = [
            "id",
            "source",
            "source_version",
            "ordinal",
            "heading_path",
            "text",
            "token_count",
            "active",
        ]


def approve_block(source: KnowledgeSource, _admin: Admin) -> str | None:
    # Temporary: the submitter may approve their own source.
    # Restore the submitted_by != approver check before this is final.
    if source.submitted_by_id is None:
        return "Submit the source before approving it."
    if source.kind == Constants.KNOWLEDGE_SOURCE_KIND_UP_SOURCE and not (
        source.licence_note or ""
    ).strip():
        return "A licence note is required before a Unified Protocol source is approved."
    if source.kind == Constants.KNOWLEDGE_SOURCE_KIND_EXERCISE_REFERENCE:
        from .indexing import read_source_text

        if duplicates_reference_material(read_source_text(source)):
            return "exercise_reference cannot copy an exercise or step reference_material."
    return None


def mark_submitted(source: KnowledgeSource, admin: Admin) -> KnowledgeSource:
    source.submitted_by = admin
    source.submitted_at = timezone.now()
    source.status = Constants.KNOWLEDGE_SOURCE_STATUS_IN_REVIEW
    source.save(
        update_fields=["submitted_by", "submitted_at", "status", "updated_at"]
    )
    return source


def mark_approved(source: KnowledgeSource, admin: Admin) -> KnowledgeSource:
    source.approved_by = admin
    source.approved_at = timezone.now()
    source.status = Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED
    source.save(update_fields=["approved_by", "approved_at", "status", "updated_at"])
    return source
