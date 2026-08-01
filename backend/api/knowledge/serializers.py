from rest_framework import serializers

from .models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ..utils import Constants
from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)


class KnowledgeFieldCreateSerializer(CreateModelSerializer):
    class Meta:
        model = KnowledgeField
        fields = [
            "key",
            "label",
            "category",
            "value_type",
            "sensitive",
            "active",
        ]

    def validate_key(self, value):
        key = (value or "").strip()
        if not key:
            raise serializers.ValidationError("This field may not be blank.")
        if KnowledgeField.objects.filter(key=key).exists():
            raise serializers.ValidationError("A knowledge field with this key already exists.")
        return key


class KnowledgeFieldEditSerializer(EditModelSerializer):
    class Meta:
        model = KnowledgeField
        fields = [
            "label",
            "category",
            "value_type",
            "sensitive",
            "active",
        ]


class KnowledgeFieldListSerializer(ListModelSerializer):
    class Meta:
        model = KnowledgeField
        fields = [
            "id",
            "key",
            "label",
            "category",
            "value_type",
            "sensitive",
            "active",
            "created_at",
            "updated_at",
        ]


class KnowledgeFieldDetailSerializer(KnowledgeFieldListSerializer):
    pass


class KnowledgeFieldBriefSerializer(ListModelSerializer):
    class Meta:
        model = KnowledgeField
        fields = ["id", "key", "label", "category", "value_type", "sensitive", "active"]


class KnowledgeQuestionCreateSerializer(CreateModelSerializer):
    suggested_responses = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
    )
    flows = serializers.ListField(
        child=serializers.ChoiceField(choices=Constants.KNOWLEDGE_FLOWS),
        required=False,
    )
    trigger_config = serializers.JSONField(required=False)

    class Meta:
        model = KnowledgeQuestion
        fields = [
            "prompt",
            "target_field",
            "trigger",
            "trigger_config",
            "suggested_responses",
            "extraction_prompt",
            "flows",
            "order",
            "active",
        ]

    def validate(self, attrs):
        trigger = attrs.get("trigger", Constants.KNOWLEDGE_TRIGGER_MANUAL_ONLY)
        trigger_config = attrs.get("trigger_config") or {}
        attrs["trigger_config"] = trigger_config

        if trigger == Constants.KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS:
            n = trigger_config.get("n")
            if n is None or not isinstance(n, int) or n < 1:
                raise serializers.ValidationError(
                    {"trigger_config": "Must include integer 'n' >= 1 when trigger is after_n_sessions."}
                )

        target_field = attrs.get("target_field")
        if target_field and not target_field.active:
            raise serializers.ValidationError(
                {"target_field": "Target field must be active."}
            )

        last = KnowledgeQuestion.objects.order_by("-order").first()
        if "order" not in attrs or attrs.get("order") is None:
            attrs["order"] = (last.order + 1) if last else 1

        return attrs


class KnowledgeQuestionEditSerializer(EditModelSerializer):
    suggested_responses = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
    )
    flows = serializers.ListField(
        child=serializers.ChoiceField(choices=Constants.KNOWLEDGE_FLOWS),
        required=False,
    )
    trigger_config = serializers.JSONField(required=False)

    class Meta:
        model = KnowledgeQuestion
        fields = [
            "prompt",
            "target_field",
            "trigger",
            "trigger_config",
            "suggested_responses",
            "extraction_prompt",
            "flows",
            "order",
            "active",
        ]

    def validate(self, attrs):
        trigger = attrs.get("trigger", self.instance.trigger)
        trigger_config = attrs.get("trigger_config", self.instance.trigger_config) or {}

        if "trigger_config" in attrs:
            attrs["trigger_config"] = trigger_config

        if trigger == Constants.KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS:
            n = trigger_config.get("n")
            if n is None or not isinstance(n, int) or n < 1:
                raise serializers.ValidationError(
                    {"trigger_config": "Must include integer 'n' >= 1 when trigger is after_n_sessions."}
                )

        target_field = attrs.get("target_field", self.instance.target_field)
        if target_field and not target_field.active:
            raise serializers.ValidationError(
                {"target_field": "Target field must be active."}
            )

        return attrs


class KnowledgeQuestionListSerializer(ListModelSerializer):
    target_field = KnowledgeFieldBriefSerializer()

    class Meta:
        model = KnowledgeQuestion
        fields = [
            "id",
            "prompt",
            "target_field",
            "trigger",
            "trigger_config",
            "suggested_responses",
            "extraction_prompt",
            "flows",
            "order",
            "active",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def optimise(queryset):
        return queryset.select_related("target_field")


class KnowledgeQuestionDetailSerializer(KnowledgeQuestionListSerializer):
    pass


class KnowledgeEntryCreateSerializer(CreateModelSerializer):
    class Meta:
        model = KnowledgeEntry
        fields = [
            "consumer",
            "field",
            "value",
            "confidence",
            "knowledge_question",
            "session",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        attrs["source"] = Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN
        if request and hasattr(request, "user") and not request.user.is_anonymous:
            attrs["created_by"] = request.user

        confidence = attrs.get("confidence", 1.0)
        if confidence is not None and (confidence < 0 or confidence > 1):
            raise serializers.ValidationError({"confidence": "Must be between 0 and 1."})

        return attrs


class KnowledgeEntryListSerializer(ListModelSerializer):
    field = KnowledgeFieldBriefSerializer()
    field_sensitive = serializers.BooleanField(source="field.sensitive", read_only=True)

    class Meta:
        model = KnowledgeEntry
        fields = [
            "id",
            "consumer",
            "field",
            "field_sensitive",
            "value",
            "source",
            "confidence",
            "knowledge_question",
            "session",
            "attribute",
            "created_by",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def optimise(queryset):
        return queryset.select_related("field", "knowledge_question", "created_by")


class KnowledgeEntryDetailSerializer(KnowledgeEntryListSerializer):
    pass


class KnowledgeExtractionTestSerializer(serializers.Serializer):
    sample_reply = serializers.CharField()
    extraction_prompt = serializers.CharField(required=False, allow_blank=True)
