from rest_framework import serializers

from .models import Setting
from ..utils import Constants


class SettingCreateSerializer(serializers.Serializer):

    survey_enabled = serializers.BooleanField()
    general_prompt = serializers.CharField()
    therapeutic_prompt = serializers.CharField()
    refresh_onboarding_cadence_days = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS,
    )
    observations_enabled = serializers.BooleanField(
        required=False,
        default=Constants.DEFAULT_OBSERVATIONS_ENABLED,
    )
    observations_instruction = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_OBSERVATIONS_INSTRUCTION,
    )
    observations_tone_guide = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_OBSERVATIONS_TONE_GUIDE,
    )
    observations_max_length = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH,
    )

    def create(self, validated_data):

        survey_setting = Setting.get_or_create_survey_enabled()
        survey_setting.value = str(validated_data.get("survey_enabled")).lower()
        survey_setting.save()

        general_prompt = Setting.get_or_create_general_prompt()
        general_prompt.value = str(validated_data.get("general_prompt"))
        general_prompt.save()

        therapeutic_prompt = Setting.get_or_create_therapeutic_prompt()
        therapeutic_prompt.value = str(validated_data.get("therapeutic_prompt"))
        therapeutic_prompt.save()

        cadence = Setting.get_or_create_refresh_onboarding_cadence_days()
        cadence.value = str(
            validated_data.get(
                "refresh_onboarding_cadence_days",
                Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS,
            )
        )
        cadence.save()

        obs_enabled = Setting.get_or_create_observations_enabled()
        obs_enabled.value = str(
            validated_data.get(
                "observations_enabled", Constants.DEFAULT_OBSERVATIONS_ENABLED
            )
        ).lower()
        obs_enabled.save()

        obs_instruction = Setting.get_or_create_observations_instruction()
        obs_instruction.value = str(
            validated_data.get(
                "observations_instruction", Constants.DEFAULT_OBSERVATIONS_INSTRUCTION
            )
        )
        obs_instruction.save()

        obs_tone = Setting.get_or_create_observations_tone_guide()
        obs_tone.value = str(
            validated_data.get(
                "observations_tone_guide", Constants.DEFAULT_OBSERVATIONS_TONE_GUIDE
            )
        )
        obs_tone.save()

        obs_max = Setting.get_or_create_observations_max_length()
        obs_max.value = str(
            validated_data.get(
                "observations_max_length", Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH
            )
        )
        obs_max.save()

        return {
            "survey_enabled": validated_data.get("survey_enabled"),
            "general_prompt": validated_data.get("general_prompt"),
            "therapeutic_prompt": validated_data.get("therapeutic_prompt"),
            "refresh_onboarding_cadence_days": int(cadence.value),
            "observations_enabled": obs_enabled.value == "true",
            "observations_instruction": obs_instruction.value,
            "observations_tone_guide": obs_tone.value,
            "observations_max_length": int(obs_max.value),
        }
