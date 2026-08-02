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

        return {
            "survey_enabled": validated_data.get("survey_enabled"),
            "general_prompt": validated_data.get("general_prompt"),
            "therapeutic_prompt": validated_data.get("therapeutic_prompt"),
            "refresh_onboarding_cadence_days": int(cadence.value),
        }

