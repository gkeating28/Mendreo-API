from ..utils.Serializers import (
    ListModelSerializer,
    EditModelSerializer,
    CreateModelSerializer
)

from .models import Tag


class TagCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Tag
        fields = [
            "name",
        ]


class TagEditSerializer(EditModelSerializer):

    class Meta:
        model = Tag
        fields = [
            "name",
        ]


class TagListSerializer(ListModelSerializer):

    class Meta:
        model = Tag
        fields = "__all__"


class TagDetailSerializer(TagListSerializer):
    pass
