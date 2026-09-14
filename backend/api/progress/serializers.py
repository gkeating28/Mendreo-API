from rest_framework import serializers

from ..utils import Constants


def _scale_answers_field():
    return serializers.ListField(
        child=serializers.IntegerField(
            min_value=Constants.SCALE_ITEM_MIN,
            max_value=Constants.SCALE_ITEM_MAX,
        ),
        min_length=Constants.SCALE_ITEM_COUNT,
        max_length=Constants.SCALE_ITEM_COUNT,
    )


class CheckInCreateSerializer(serializers.Serializer):
    anxiety = _scale_answers_field()
    positive_emotion = _scale_answers_field()
