import json

from rest_framework import serializers

from .models import Setting
from ..utils import Constants
from ..utils.authoring import PROMPT_SETTING_FIELDS


class SettingCreateSerializer(serializers.Serializer):

    survey_enabled = serializers.BooleanField()
    general_prompt = serializers.CharField(required=False)
    therapeutic_prompt = serializers.CharField(required=False)
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
    knowledge_min_confidence = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1,
    )
    history_max_turns = serializers.IntegerField(required=False, min_value=1)
    session_inactivity_minutes = serializers.IntegerField(required=False, min_value=1)
    thin_answer_min_words = serializers.IntegerField(required=False, min_value=1)
    generic_answers_default = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    risk_keywords = serializers.JSONField(required=False)
    trust_and_safety_email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, attrs):
        incoming = set(getattr(self, "initial_data", {}) or {})
        blocked = [name for name in PROMPT_SETTING_FIELDS if name in incoming]
        if blocked:
            raise serializers.ValidationError(
                {
                    name: "Save this text as a prompt version, not a setting."
                    for name in blocked
                }
            )
        return attrs

    def create(self, validated_data):

        survey_setting = Setting.get_or_create_survey_enabled()
        survey_setting.value = str(validated_data.get("survey_enabled")).lower()
        survey_setting.save()

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

        obs_max = Setting.get_or_create_observations_max_length()
        obs_max.value = str(
            validated_data.get(
                "observations_max_length", Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH
            )
        )
        obs_max.save()

        if "knowledge_min_confidence" in validated_data:
            confidence = Setting.get_or_create_knowledge_min_confidence()
            confidence.value = str(validated_data["knowledge_min_confidence"])
            confidence.save()

        if "history_max_turns" in validated_data:
            turns = Setting.get_or_create_history_max_turns()
            turns.value = str(validated_data["history_max_turns"])
            turns.save()

        if "session_inactivity_minutes" in validated_data:
            idle = Setting.get_or_create_session_inactivity_minutes()
            idle.value = str(validated_data["session_inactivity_minutes"])
            idle.save()

        if "thin_answer_min_words" in validated_data:
            words = Setting.get_or_create_thin_answer_min_words()
            words.value = str(validated_data["thin_answer_min_words"])
            words.save()

        if "generic_answers_default" in validated_data:
            generic = Setting.get_or_create_generic_answers_default()
            generic.value = json.dumps(validated_data["generic_answers_default"])
            generic.save()

        if "risk_keywords" in validated_data:
            keywords = Setting.get_or_create_risk_keywords()
            keywords.value = json.dumps(validated_data["risk_keywords"])
            keywords.save()

        if "trust_and_safety_email" in validated_data:
            address = Setting.get_or_create_trust_and_safety_email()
            address.value = validated_data["trust_and_safety_email"] or ""
            address.save()

        return {
            "survey_enabled": validated_data.get("survey_enabled"),
            "refresh_onboarding_cadence_days": int(cadence.value),
            "observations_enabled": obs_enabled.value == "true",
            "observations_max_length": int(obs_max.value),
            "knowledge_min_confidence": Setting.get_knowledge_min_confidence(),
            "history_max_turns": Setting.get_history_max_turns(),
            "session_inactivity_minutes": Setting.get_session_inactivity_minutes(),
            "thin_answer_min_words": Setting.get_thin_answer_min_words(),
            "generic_answers_default": Setting.get_generic_answers_default(),
            "risk_keywords": Setting.get_risk_keywords(),
            "trust_and_safety_email": Setting.get_trust_and_safety_email(),
        }
