from rest_framework import serializers
from django.db.models import F

from .models import Exercise

from ..step.serializers import (
    StepCreateSerializer,
    StepEditSerializer,
    StepDetailSerializer,
    StepAdminDetailSerializer,
)

from ..question.serializers import (
    QuestionEditSerializer,
    QuestionExerciseCreateSerializer,
    QuestionExerciseDetailSerializer,
)

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..utils import Constants
from ..utils import Duplicate


class ExerciseCreateSerializer(CreateModelSerializer):

    steps = StepCreateSerializer(
        many=True,
        allow_empty=False,
        nested_relation=True,
        related_name="steps",
        model_name_in_related_object="exercise",
        edit_serializer=StepEditSerializer,
        create_serializer=StepCreateSerializer,
    )

    questions = QuestionExerciseCreateSerializer(
        many=True,
        nested_relation=True,
        related_name="questions",
        model_name_in_related_object="exercise",
        edit_serializer=QuestionEditSerializer,
        create_serializer=QuestionExerciseCreateSerializer,
    )

    status = serializers.ChoiceField(choices=Constants.EXERCISE_STATUSES)

    class Meta:
        model = Exercise
        fields = [
            "title",
            "subtitle",
            "description",
            "status",
            "icon",
            "icon_svg",
            "icon_background_color",
            "steps",
            "questions",
        ]

    def validate(self, attrs):
        last_exercise = Exercise.objects.order_by("-order").first()
        attrs["order"] = last_exercise.order + 1 if last_exercise else 1

        attrs = steps_validation(self, attrs)
        return attrs

    def post_create(self, model, nested_relations):
        """Recalculate average duration after steps are created."""
        if "steps" in nested_relations:
            model._update_average_duration()


class ExerciseEditSerializer(EditModelSerializer):

    steps = StepCreateSerializer(
        many=True,
        nested_relation=True,
        related_name="steps",
        model_name_in_related_object="exercise",
        edit_serializer=StepEditSerializer,
        create_serializer=StepCreateSerializer,
    )

    questions = QuestionExerciseCreateSerializer(
        many=True,
        nested_relation=True,
        related_name="questions",
        model_name_in_related_object="exercise",
        edit_serializer=QuestionEditSerializer,
        create_serializer=QuestionExerciseCreateSerializer,
    )

    class Meta:
        model = Exercise
        fields = [
            "title",
            "subtitle",
            "description",
            "status",
            "icon",
            "icon_svg",
            "icon_background_color",
            "steps",
            "questions",
            "order",
        ]

    def validate(self, attrs):
        attrs = order_validation(self, attrs)
        attrs = steps_validation(self, attrs)
        return attrs

    def post_update(self, model, nested_relations):
        """Recalculate average duration after steps are updated."""
        if "steps" in nested_relations:
            model._update_average_duration()


class ExerciseListSerializer(ListModelSerializer):
    class Meta:
        model = Exercise
        fields = [
            "id",
            "title",
            "subtitle",
            "icon",
            "icon_svg",
            "icon_background_color",
            "steps_no",
            "order",
            "created_at",
            "updated_at",
            "average_duration",
        ]


class ExerciseDetailSerializer(ExerciseListSerializer):
    steps = StepDetailSerializer(many=True, order_by="order")
    questions = QuestionExerciseDetailSerializer(many=True, order_by="order")

    class Meta(ExerciseListSerializer.Meta):
        ExerciseListSerializer.Meta.fields += [
            "steps",
            "questions",
        ]


class ExerciseAdminListSerializer(ExerciseListSerializer):
    class Meta(ExerciseListSerializer.Meta):
        fields = ExerciseListSerializer.Meta.fields + [
            "status",
            "description",
            "completions_no",
        ]


class ExerciseAdminDetailSerializer(ExerciseAdminListSerializer):
    steps = StepAdminDetailSerializer(many=True, order_by="order")
    questions = QuestionExerciseDetailSerializer(many=True, order_by="order")

    class Meta(ExerciseAdminListSerializer.Meta):
        fields = ExerciseAdminListSerializer.Meta.fields + [
            "steps",
            "questions",
        ]

    @classmethod
    def get_prefetch_related_fields(cls):
        return [
            "steps",
            "questions",
        ]


def steps_validation(serializer, attrs) -> dict:
    steps = attrs.get("steps", None)
    if not steps:
        steps = serializer.instance.steps.all()

    attrs["steps_no"] = len(steps)

    return attrs


def order_validation(serializer, attrs):
    order = attrs.get("order")

    if order is not None:
        Exercise.objects.filter(order__gte=order).update(order=F("order") + 1)

    return attrs


class ExerciseDuplicateSerializer(serializers.Serializer):
    exercise = serializers.PrimaryKeyRelatedField(
        queryset=Exercise.objects.all(),)

    name = serializers.CharField()

    def create(self, validated_data):
        source = validated_data.get("exercise")
        new_name = validated_data.get("name")

        EXCLUSION_FIELDS = [
            "completions_no"
        ]

        exercise = Duplicate.instance(source, exclude_fields=EXCLUSION_FIELDS)

        exercise.title = new_name
        exercise.status = Constants.EXERCISE_STATUS_DRAFT

        exercise.save()

        exercise._update_average_duration()

        return exercise

