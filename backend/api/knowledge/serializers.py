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
        confidence = attrs.get("confidence", 1.0)
        if confidence is not None and (confidence < 0 or confidence > 1):
            raise serializers.ValidationError({"confidence": "Must be between 0 and 1."})

        return attrs

    def create(self, validated_data):
        from .services import write_knowledge_entry

        request = self.context.get("request")
        created_by = None
        if request and hasattr(request, "user") and not request.user.is_anonymous:
            created_by = request.user

        return write_knowledge_entry(
            consumer=validated_data["consumer"],
            field=validated_data["field"],
            value=validated_data["value"],
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
            confidence=validated_data.get("confidence", 1.0),
            knowledge_question=validated_data.get("knowledge_question"),
            session=validated_data.get("session"),
            created_by=created_by,
        )


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


class KnowledgeProfileEditItemSerializer(serializers.Serializer):
    field_id = serializers.CharField()
    value = serializers.CharField()
    confidence = serializers.FloatField(required=False, default=1.0, min_value=0, max_value=1)


class KnowledgeProfileEditSerializer(serializers.Serializer):
    """
    PATCH body for admin edits. Accepts either a single field edit or a list under `entries`.
    Each edit appends a new KnowledgeEntry with source=admin.
    """

    field_id = serializers.CharField(required=False)
    value = serializers.CharField(required=False)
    confidence = serializers.FloatField(required=False, default=1.0, min_value=0, max_value=1)
    entries = KnowledgeProfileEditItemSerializer(many=True, required=False)

    def validate(self, attrs):
        entries = attrs.get("entries")
        if entries:
            return {"entries": entries}

        field_id = attrs.get("field_id")
        value = attrs.get("value")
        if not field_id or value is None:
            raise serializers.ValidationError(
                "Provide either 'entries' or both 'field_id' and 'value'."
            )

        return {
            "entries": [
                {
                    "field_id": field_id,
                    "value": value,
                    "confidence": attrs.get("confidence", 1.0),
                }
            ]
        }


class KnowledgeActivitySerializer(ListModelSerializer):
    field = KnowledgeFieldBriefSerializer()
    field_sensitive = serializers.BooleanField(source="field.sensitive", read_only=True)

    class Meta:
        model = KnowledgeEntry
        fields = [
            "id",
            "field",
            "field_sensitive",
            "value",
            "source",
            "confidence",
            "knowledge_question",
            "session",
            "created_by",
            "created_at",
        ]

    @staticmethod
    def optimise(queryset):
        return queryset.select_related("field", "knowledge_question", "session", "created_by")
