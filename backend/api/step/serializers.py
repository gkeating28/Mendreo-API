from rest_framework import serializers

from .models import Step
from ..utils import Constants
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

    def to_internal_value(self, data):
        # An existing step is validated again by StepEditSerializer, which is
        # built on its own and cannot see the exercise payload. Copy the status
        # from this save so a draft can update a step that is still published.
        if isinstance(data, dict):
            data = dict(data)
            # Drop a client-supplied copy before reading the exercise status.
            data.pop("_exercise_status", None)
            status = _exercise_status(self, trust_stamp=False)
            if status is not None:
                data["_exercise_status"] = status
        return super().to_internal_value(data)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        _raise_step_wording_errors(self, attrs)
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
        _raise_step_wording_errors(self, attrs)
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


def _exercise_status(serializer, *, trust_stamp=True):
    """Status for this save.

    A nested step sees the exercise serializer. A step rechecked on its own
    sees the status this save copied onto its data, or the exercise row it
    already belongs to. The copied value is only trusted after the create
    serializer has removed any client-supplied one.
    """
    root = serializer.root
    if root is not None and root is not serializer:
        initial = getattr(root, "initial_data", None)
        if isinstance(initial, dict) and initial.get("status"):
            return initial.get("status")
        exercise = getattr(root, "instance", None)
        status = getattr(exercise, "status", None)
        if status:
            return status

    if trust_stamp:
        initial = getattr(serializer, "initial_data", None)
        if isinstance(initial, dict) and initial.get("_exercise_status"):
            return initial.get("_exercise_status")

    step = getattr(serializer, "instance", None)
    exercise = getattr(step, "exercise", None) if step is not None else None
    return getattr(exercise, "status", None)


def _raise_step_wording_errors(serializer, attrs):
    """Wording rules apply when publishing. Draft and archived saves skip them.

    A step save that is not part of an exercise save keeps today's checks.
    """
    status = _exercise_status(serializer)
    if status in (
        Constants.EXERCISE_STATUS_DRAFT,
        Constants.EXERCISE_STATUS_ARCHIVED,
    ):
        return
    errors = step_field_errors(_merged_step(serializer.instance, attrs))
    if errors:
        raise serializers.ValidationError(errors)


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
