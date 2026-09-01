from .models import Attribute

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..question.serializers import QuestionListSerializer

from ..utils import Constants

from datetime import datetime


class AttributeCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Attribute
        fields = [
            "value",
            "question",
            "consumer",
        ]

    def validate(self, attrs):

        attrs = consumer_validation(self, attrs)
        attrs = value_validation(self, attrs)

        attrs["key"] = attrs["question"].attribute_key

        return attrs

    def post_create(self, attribute, nested_relations: dict):

        consumer = attribute.consumer
        question = attribute.question
        value = attribute.value

        if question.can_complete_exercise and value.lower() == question.complete_on_value.lower():
            session = question.session
            if session and not session.completed:
                session.mark_completed()
                session.save(update_fields=["completed", "completed_at", "updated_at"])

        if not consumer.onboarded:
            consumer.update_onboarding_status()

        if not consumer.surveyed and question.survey:
            consumer.update_surveyed_status()

        return





class AttributeEditSerializer(EditModelSerializer):

    class Meta:
        model = Attribute
        fields = [
            "value",
        ]


class AttributeListSerializer(ListModelSerializer):

    class Meta:
        model = Attribute
        fields = [
            "id",
            "key",
            "value",
            "question",
        ]


class AttributeDetailSerializer(AttributeListSerializer):

    question = QuestionListSerializer()

    @classmethod
    def get_select_related_fields(cls):
        return ["question"]


def consumer_validation(serializer, attrs):
    consumer = attrs.get("consumer")
    question = attrs.get("question")

    if Attribute.objects.filter(consumer=consumer, question=question).exists():
        raise serializer.raise_validation_error("question", "has already been answered")

    return attrs


def value_validation(serializer, attrs):
    value = attrs.get("value")
    question = attrs.get("question", serializer.instance.question if serializer.instance else None)
    type_ = question.type
    suggested_responses = question.suggested_responses or []

    valid_boolean_options = Constants.ATTRIBUTE_TYPE_BOOLEAN_VALID_OPTIONS
    if type_ == Constants.QUESTION_TYPE_BOOLEAN and value.lower() not in valid_boolean_options:
        raise serializer.raise_validation_error("value", f"must be one of: {valid_boolean_options}")

    if type_ == Constants.QUESTION_TYPE_NUMBER:
        try:
            int(value)
        except Exception as e:
            serializer.raise_validation_error("value", f"'{value}' is not a valid number")

    if type_ == Constants.QUESTION_TYPE_SLIDER:
        try:
            number = int(value)
        except Exception:
            serializer.raise_validation_error(
                "value", f"'{value}' is not a valid slider value"
            )
        if number < Constants.SLIDER_MIN or number > Constants.SLIDER_MAX:
            serializer.raise_validation_error(
                "value",
                f"must be an integer between {Constants.SLIDER_MIN} and {Constants.SLIDER_MAX}",
            )

    if type_ == Constants.QUESTION_TYPE_DATE:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except Exception as e:
            serializer.raise_validation_error("value", f"'{value}' is not a valid data in format 'YYYY-MM-DD")

    if type_ == Constants.QUESTION_TYPE_SINGLE_CHOICE:
        if value not in suggested_responses:
            serializer.raise_validation_error("value", f"'{value}' is not a valid option")

    if type_ == Constants.QUESTION_TYPE_MULTIPLE_CHOICE:
        values = [v.strip() for v in value.split(",") if v.strip()]
        for item in values:
            if item not in suggested_responses:
                serializer.raise_validation_error("value", f"'{item}' is not a valid option")
        min_selections = question.min_selections
        max_selections = question.max_selections
        count = len(values)
        if min_selections is not None and count < min_selections:
            serializer.raise_validation_error(
                "value", f"must select at least {min_selections} option(s)"
            )
        if max_selections is not None and count > max_selections:
            serializer.raise_validation_error(
                "value", f"must select at most {max_selections} option(s)"
            )

    return attrs
