from rest_framework import serializers

from .models import MoodEntry
from ..consumer.models import Consumer
from ..utils import Constants
from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)


class MoodEntryCreateSerializer(CreateModelSerializer):
    mood_score = serializers.IntegerField(
        min_value=Constants.MOOD_SCORE_MIN,
        max_value=Constants.MOOD_SCORE_MAX,
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    consumer = serializers.PrimaryKeyRelatedField(queryset=Consumer.objects.all())

    class Meta:
        model = MoodEntry
        fields = [
            "consumer",
            "mood_score",
            "note",
        ]


class MoodEntryEditSerializer(EditModelSerializer):
    mood_score = serializers.IntegerField(
        min_value=Constants.MOOD_SCORE_MIN,
        max_value=Constants.MOOD_SCORE_MAX,
        required=False,
    )
    note = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = MoodEntry
        fields = [
            "mood_score",
            "note",
        ]


class MoodEntryListSerializer(ListModelSerializer):
    mood_label = serializers.CharField(read_only=True)

    class Meta:
        model = MoodEntry
        fields = [
            "id",
            "consumer",
            "mood_score",
            "mood_label",
            "note",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return ["consumer"]


class MoodEntryDetailSerializer(MoodEntryListSerializer):
    pass
