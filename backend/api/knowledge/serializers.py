from django.db.models import Count, Q
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


def _normalize_order_by_flow(order_by_flow):
    if order_by_flow is None:
        return {}
    if not isinstance(order_by_flow, dict):
        raise serializers.ValidationError(
            {"order_by_flow": "Must be an object mapping flow → order integer."}
        )
    normalized = {}
    for key, value in order_by_flow.items():
        if key not in Constants.KNOWLEDGE_FLOWS:
            raise serializers.ValidationError(
                {"order_by_flow": f"Unknown flow '{key}'."}
            )
        try:
            normalized[key] = int(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"order_by_flow": f"Order for '{key}' must be an integer."}
            )
    return normalized


def response_control_validation(attrs, instance=None):
    """Validate slider labels and multi-select bounds for knowledge questions."""
    response_type = attrs.get(
        "response_type",
        getattr(instance, "response_type", Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT),
    )
    suggested = attrs.get(
        "suggested_responses",
        getattr(instance, "suggested_responses", None) if instance else None,
    )
    if suggested is None:
        suggested = []

    anchor_labels = attrs.get(
        "anchor_labels",
        getattr(instance, "anchor_labels", None) if instance else None,
    )
    value_labels = attrs.get(
        "value_labels",
        getattr(instance, "value_labels", None) if instance else None,
    )
    min_selections = attrs.get(
        "min_selections",
        getattr(instance, "min_selections", None) if instance else None,
    )
    max_selections = attrs.get(
        "max_selections",
        getattr(instance, "max_selections", None) if instance else None,
    )

    errors = {}

    if response_type in (
        Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE,
        Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE,
    ):
        if len(suggested) < 2:
            errors["suggested_responses"] = (
                f"'{response_type}' must have at least 2 suggested_responses"
            )

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER:
        if anchor_labels is None:
            attrs["anchor_labels"] = [
                Constants.SLIDER_DEFAULT_ANCHOR_LEFT,
                Constants.SLIDER_DEFAULT_ANCHOR_RIGHT,
            ]
        elif len(anchor_labels) != 2:
            errors["anchor_labels"] = "Must contain exactly 2 labels (left, right)."
        if value_labels is not None and len(value_labels) > Constants.SLIDER_VALUE_LABEL_COUNT:
            errors["value_labels"] = (
                f"Must contain at most {Constants.SLIDER_VALUE_LABEL_COUNT} labels."
            )
        elif value_labels is not None and len(value_labels) < Constants.SLIDER_VALUE_LABEL_COUNT:
            # Pad to 11 so clients can index by slider position.
            padded = list(value_labels) + [""] * (
                Constants.SLIDER_VALUE_LABEL_COUNT - len(value_labels)
            )
            attrs["value_labels"] = padded

    if response_type != Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE:
        if "min_selections" in attrs and attrs["min_selections"] is not None:
            errors["min_selections"] = "Only valid for multiple_choice response_type."
        if "max_selections" in attrs and attrs["max_selections"] is not None:
            errors["max_selections"] = "Only valid for multiple_choice response_type."
    else:
        if min_selections is not None and max_selections is not None:
            if min_selections > max_selections:
                errors["min_selections"] = "Cannot be greater than max_selections."
        if max_selections is not None and suggested and max_selections > len(suggested):
            errors["max_selections"] = "Cannot exceed number of suggested_responses."

    if errors:
        raise serializers.ValidationError(errors)

    return attrs


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
    order_by_flow = serializers.JSONField(required=False)
    anchor_labels = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        allow_null=True,
    )
    value_labels = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        allow_null=True,
    )

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
            "order_by_flow",
            "response_type",
            "anchor_labels",
            "value_labels",
            "min_selections",
            "max_selections",
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

        if "order_by_flow" in attrs:
            attrs["order_by_flow"] = _normalize_order_by_flow(attrs.get("order_by_flow"))

        attrs = response_control_validation(attrs)

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
    order_by_flow = serializers.JSONField(required=False)
    anchor_labels = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        allow_null=True,
    )
    value_labels = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        allow_null=True,
    )

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
            "order_by_flow",
            "response_type",
            "anchor_labels",
            "value_labels",
            "min_selections",
            "max_selections",
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

        if "order_by_flow" in attrs:
            attrs["order_by_flow"] = _normalize_order_by_flow(attrs.get("order_by_flow"))

        attrs = response_control_validation(attrs, instance=self.instance)

        return attrs


class KnowledgeQuestionListSerializer(ListModelSerializer):
    target_field = KnowledgeFieldBriefSerializer()
    entry_count = serializers.IntegerField(read_only=True, default=0)

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
            "order_by_flow",
            "response_type",
            "anchor_labels",
            "value_labels",
            "min_selections",
            "max_selections",
            "order",
            "active",
            "created_at",
            "updated_at",
            "entry_count",
        ]

    @staticmethod
    def optimise(queryset):
        return queryset.select_related("target_field").annotate(
            entry_count=Count("entries", filter=Q(entries__deleted_at__isnull=True))
        )


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
