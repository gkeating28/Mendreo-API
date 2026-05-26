from rest_framework import serializers

from .models import Setting


class SettingCreateSerializer(serializers.Serializer):

    survey_enabled = serializers.BooleanField()
    general_prompt = serializers.CharField()
    therapeutic_prompt = serializers.CharField()

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

        return validated_data

