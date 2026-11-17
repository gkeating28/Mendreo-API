from rest_framework import serializers

from ..user.models import UserSettings
from .defaults import BODY_MAX, STEP_IDS, TITLE_MAX


class TourStepWriteSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=TITLE_MAX,
    )
    body = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=BODY_MAX,
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = set(data) - {"id", "title", "body"}
            if unknown:
                raise serializers.ValidationError({
                    name: "This field is not editable."
                    for name in sorted(unknown)
                })
        return super().to_internal_value(data)


class TourConfigSerializer(serializers.Serializer):
    steps = TourStepWriteSerializer(many=True)

    def validate_steps(self, steps):
        seen = set()
        for step in steps:
            step_id = step["id"]
            if step_id not in STEP_IDS:
                raise serializers.ValidationError(f"Unknown step id: {step_id}.")
            if step_id in seen:
                raise serializers.ValidationError(f"Duplicate step id: {step_id}.")
            seen.add(step_id)
        return steps


class TourAudioSerializer(serializers.Serializer):
    voice_id = serializers.CharField(required=False, allow_blank=True)

    def validate_voice_id(self, value):
        voice_id = (value or "").strip()
        if not voice_id:
            return UserSettings.VoiceId.FEMALE_IRISH
        if voice_id not in UserSettings.VoiceId.values:
            raise serializers.ValidationError(
                "Must be one of: " + ", ".join(UserSettings.VoiceId.values),
            )
        return voice_id
