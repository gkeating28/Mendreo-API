from rest_framework import serializers

from .models import Step
from ..utils.authoring import step_field_errors

from ..tag.serializers import Tag, TagListSerializer

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)


class StepCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Step
        fields = [
            "tags",
            "title",
            "description",
            "instructions",
            "completion_label",
            "completion_prompt",
            "key",
            "reference_material",
            "done_when",
            "result_field",
            "average_duration",
            "success_title",
        ]
        extra_kwargs = {
            "completion_prompt": {"required": False, "allow_null": True, "allow_blank": True},
            "key": {"required": False, "allow_null": True, "allow_blank": True},
            "reference_material": {"required": False, "allow_null": True, "allow_blank": True},
            "done_when": {"required": False, "allow_null": True, "allow_blank": True},
            "result_field": {"required": False, "allow_null": True},
            "average_duration": {"required": False},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        errors = step_field_errors(_merged_step(self.instance, attrs))
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class StepEditSerializer(EditModelSerializer):

    class Meta:
        model = Step
        fields = [
            "tags",
            "title",
            "description",
            "instructions",
            "completion_label",
            "completion_prompt",
            "key",
            "reference_material",
            "done_when",
            "result_field",
            "average_duration",
            "success_title",
        ]
        extra_kwargs = {
            "completion_prompt": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        errors = step_field_errors(_merged_step(self.instance, attrs))
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class StepListSerializer(ListModelSerializer):

    class Meta:
        model = Step
        fields = [
            "id",
            "title",
            "description",
            "average_duration",
            "success_title",
        ]


class StepDetailSerializer(StepListSerializer):
    pass


class StepAdminListSerializer(StepListSerializer):

    tags = TagListSerializer(many=True)

    class Meta(StepListSerializer.Meta):
        fields = [
            "id",
            "tags",
            "title",
            "description",
            "instructions",
            "completion_label",
            "completion_prompt",
            "key",
            "reference_material",
            "done_when",
            "result_field",
            "result_field_key",
            "average_duration",
            "success_title",
        ]

    result_field_key = serializers.SerializerMethodField()

    def get_result_field_key(self, step):
        field = getattr(step, "result_field", None)
        return field.key if field else None

    @classmethod
    def get_prefetch_related_fields(cls):
        return ["tags"]

    @classmethod
    def get_select_related_fields(cls):
        return ["result_field"]


def _merged_step(instance, attrs) -> dict:
    def value(name):
        if name in attrs:
            return attrs[name]
        if instance is not None:
            return getattr(instance, name, None)
        return None

    result_field = value("result_field")
    return {
        "instructions": value("instructions") or "",
        "done_when": value("done_when") or "",
        "completion_prompt": value("completion_prompt") or "",
        "result_field": getattr(result_field, "id", result_field),
        "average_duration": value("average_duration"),
    }


class StepAdminDetailSerializer(StepAdminListSerializer):
    pass
