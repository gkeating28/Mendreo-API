from rest_framework import serializers

from .models import Step

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
            "completion_criteria",
            "completion_label",
            "completion_prompt",
            "success_title"
        ]


class StepEditSerializer(EditModelSerializer):

    class Meta:
        model = Step
        fields = [
            "tags",
            "title",
            "description",
            "instructions",
            "completion_criteria",
            "completion_label",
            "completion_prompt",
            "average_duration",

            "success_title"
        ]


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
            "completion_criteria",
            "completion_label",
            "completion_prompt",
            "average_duration",
            "success_title",
        ]

    @classmethod
    def get_prefetch_related_fields(cls):
        return ["tags"]


class StepAdminDetailSerializer(StepAdminListSerializer):
    pass
