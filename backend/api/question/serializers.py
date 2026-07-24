from rest_framework import serializers

from .models import Question
from django.db.models import F

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..utils import Constants

from datetime import datetime


class QuestionCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Question
        fields = [
            "type",
            "title",
            "attribute_key",
            "suggested_responses",
            "survey",
        ]

    def validate(self, attrs):

        last_question = Question.objects.order_by("-order").first()
        attrs["order"] = last_question.order + 1 if last_question else 1
        attrs = type_validation(self, attrs)

        return attrs


class QuestionExerciseCreateSerializer(QuestionCreateSerializer):

    pre_exercise = serializers.BooleanField()
    suggested_responses = serializers.ListField(child=serializers.CharField())
    can_complete_exercise = serializers.BooleanField(required=False, default=False)
    complete_on_value = serializers.CharField(required=False, allow_null=True)
    complete_text = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = Question
        fields = QuestionCreateSerializer.Meta.fields + [
            "pre_exercise",
            "can_complete_exercise",
            "complete_on_value",
            "complete_text",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        attrs = can_complete_validation(self, attrs)
        return attrs


class QuestionEditSerializer(EditModelSerializer):

    class Meta:
        model = Question
        fields = [
            "title",
            "order",
            "suggested_responses",
            "can_complete_exercise",
            "pre_exercise",
            "complete_on_value",
            "complete_text"
        ]

    def validate(self, attrs):
        attrs["type"] = self.instance.type

        attrs = order_validation(self, attrs)
        attrs = type_validation(self, attrs)
        attrs = can_complete_validation(self, attrs)

        return attrs


class QuestionListSerializer(ListModelSerializer):

    class Meta:
        model = Question
        fields = [
            "id",
            "type",
            "title",
            "order",
            "survey",
            "attribute_key",
            "suggested_responses",
        ]


class QuestionDetailSerializer(QuestionListSerializer):
    pass


class QuestionExerciseDetailSerializer(ListModelSerializer):

    class Meta:
        model = Question
        fields = [
            "id",
            "type",
            "title",
            "order",
            "pre_exercise",
            "attribute_key",
            "suggested_responses",
            "can_complete_exercise",
            "complete_on_value",
            "complete_text"
        ]


def order_validation(serializer, attrs):
    order = attrs.get("order")

    if order is not None:
        is_survey_question = serializer.instance.survey

        Question.objects.filter(survey=is_survey_question, order__gte=order).update(order=F('order') + 1)

    return attrs


def type_validation(serializer, attrs):
    type_ = attrs.get("type")
    suggested_responses = attrs.get("suggested_responses", [])

    if type_ == Constants.QUESTION_TYPE_BOOLEAN and len(suggested_responses) != 0:
        raise serializer.raise_validation_error("type", f"'{type_}' can not have 'suggested_responses'")

    if type_ in [Constants.QUESTION_TYPE_SINGLE_CHOICE, Constants.QUESTION_TYPE_MULTIPLE_CHOICE] and len(suggested_responses) < 2:
        raise serializer.raise_validation_error("type", f"'{type_}' must have at least 2 'suggested_responses'")

    errors = []
    for suggested_response in suggested_responses:
        if type_ == Constants.QUESTION_TYPE_NUMBER:
            try:
                int(suggested_response)
            except Exception as e:
                errors.append(f"'{suggested_response}' is not a valid number")

        if type_ == Constants.QUESTION_TYPE_DATE:
            try:
                datetime.strptime(suggested_response, "%Y-%m-%d")
            except Exception as e:
                errors.append(f"'{suggested_response}' is not a valid data in format 'YYYY-MM-DD")

    if errors:
        raise serializer.raise_validation_error("suggested_responses", errors)

    return attrs


def can_complete_validation(serializer, attrs):
    type_ = attrs.get("type")
    can_complete_exercise = attrs.get("can_complete_exercise")
    complete_on_value = attrs.get("complete_on_value")
    complete_text = attrs.get("complete_text")
    pre_exercise = attrs.get("pre_exercise")

    question = serializer.instance

    if question:
        type_ = question.type
        pre_exercise = question.pre_exercise

        if "can_complete_exercise" not in attrs:
            can_complete_exercise = question.can_complete_exercise
        if "complete_on_value" not in attrs:
            complete_on_value = question.complete_on_value
        if "complete_text" not in attrs:
            complete_text = question.complete_text

    if not can_complete_exercise and not complete_on_value and not complete_text:
        return attrs

    if type_ != Constants.QUESTION_TYPE_BOOLEAN:
        if can_complete_exercise:
            raise serializer.raise_validation_error(
                "can_complete_exercise",
                f"This field is cannot be true for type {type_}",
            )

        if complete_on_value:
            raise serializer.raise_validation_error(
                "complete_on_value",
                f"This field is cannot be specified for type {type_}",
            )

        if complete_text:
            raise serializer.raise_validation_error(
                "complete_text",
                f"This field is cannot be specified for type {type_}",
            )

        return attrs

    if not complete_on_value:
        raise serializer.raise_validation_error(
            "complete_on_value",
            "This field is required when 'can_complete_exercise' is True",
        )

    if not can_complete_exercise:
        raise serializer.raise_validation_error(
            "can_complete_exercise",
            "This field must be True when 'complete_on_value' is set",
        )

    if not complete_text:
        raise serializer.raise_validation_error(
            "complete_text",
            "This field is required when 'can_complete_exercise' is True",
        )

    if type_ != Constants.QUESTION_TYPE_BOOLEAN:
        raise serializer.raise_validation_error(
            "can_complete_exercise",
            f"Can only be set for '{Constants.QUESTION_TYPE_BOOLEAN}' type questions"
        )

    if pre_exercise is not True:
        raise serializer.raise_validation_error(
            "pre_exercise",
            f"Must be true if 'can_complete_exercise' is True"
        )

    valid_boolean_options = Constants.ATTRIBUTE_TYPE_BOOLEAN_VALID_OPTIONS
    if complete_on_value.lower() not in valid_boolean_options:
        raise serializer.raise_validation_error(
            "complete_on_value",
            f"must be one of: {valid_boolean_options}"
        )

    return attrs
