from rest_framework import serializers

from .models import Feedback, User, Message

from ..user.serializers import UserDetailSerializer

from ..utils.Serializers import (
    CreateModelSerializer,
    ListModelSerializer,
)


class FeedbackCreateSerializer(CreateModelSerializer):

    positive = serializers.BooleanField()
    message = serializers.PrimaryKeyRelatedField(queryset=Message.objects.all())

    class Meta:
        model = Feedback
        fields = [
            "message",
            "positive",
            "reason",
        ]


class FeedbackUserCreateSerializer(CreateModelSerializer):

    value = serializers.CharField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())

    class Meta:
        model = Feedback
        fields = [
            "user",
            "value",
        ]


class FeedbackListSerializer(ListModelSerializer):

    user = UserDetailSerializer()

    class Meta:
        model = Feedback
        fields = [
            "id",
            "message",
            "positive",
            "reason",
            "value",
            "user",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return [
            "user"
        ]


class FeedbackDetailSerializer(FeedbackListSerializer):
    pass
