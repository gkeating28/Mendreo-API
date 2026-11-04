from __future__ import unicode_literals

from rest_framework import status
from rest_framework.response import Response

from .models import Setting
from ..utils import Constants

from .serializers import (
    SettingCreateSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
)

from ..utils.Views import SmartAPIView


class ListCreate(SmartAPIView):

    permission_classes = [IsAdminPermission]

    def get(self, request):

        settings = Setting.objects.all()

        data = {}

        for setting in settings:
            data[setting.key] = setting.value

            if setting.key in (
                "survey_enabled",
                "observations_enabled",
                Constants.SETTING_KEY_INSIGHTS_ENABLED,
                Constants.SETTING_KEY_STORE_TURN_PROMPTS,
                Constants.SETTING_KEY_CHAT_DEBUG_ENABLED,
                Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED,
                Constants.SETTING_KEY_AI_RETRIEVAL_EXERCISE_ENABLED,
            ):
                data[setting.key] = setting.value.lower() == "true"
            elif setting.key == Constants.SETTING_KEY_KNOWLEDGE_MIN_CONFIDENCE:
                try:
                    data[setting.key] = float(setting.value)
                except (TypeError, ValueError):
                    data[setting.key] = Setting.get_knowledge_min_confidence()
            elif setting.key in (
                Constants.SETTING_KEY_HISTORY_MAX_TURNS,
                Constants.SETTING_KEY_THIN_ANSWER_MIN_WORDS,
                Constants.SETTING_KEY_SESSION_INACTIVITY_MINUTES,
            ):
                try:
                    data[setting.key] = int(setting.value)
                except (TypeError, ValueError):
                    data[setting.key] = (
                        Setting.get_history_max_turns()
                        if setting.key == Constants.SETTING_KEY_HISTORY_MAX_TURNS
                        else Setting.get_thin_answer_min_words()
                        if setting.key == Constants.SETTING_KEY_THIN_ANSWER_MIN_WORDS
                        else Setting.get_session_inactivity_minutes()
                    )
            elif setting.key == Constants.SETTING_KEY_GENERIC_ANSWERS_DEFAULT:
                data[setting.key] = Setting.get_generic_answers_default()
            elif setting.key == Constants.SETTING_KEY_CHAT_OPENERS:
                data[setting.key] = Setting.get_chat_openers()
            elif setting.key == Constants.SETTING_KEY_RISK_KEYWORDS:
                data[setting.key] = Setting.get_risk_keywords()
            elif setting.key in (
                "refresh_onboarding_cadence_days",
                "observations_max_length",
                Constants.SETTING_KEY_RUN_SUMMARY_MAX_LENGTH,
                Constants.SETTING_KEY_INSIGHTS_POOL_CAP,
                Constants.SETTING_KEY_INSIGHTS_SHOWN_COUNT,
                Constants.SETTING_KEY_INSIGHTS_RECENT_RUNS,
                Constants.SETTING_KEY_INSIGHTS_MIN_POOL_BEFORE_SHUFFLE,
                Constants.SETTING_KEY_INSIGHTS_MAX_LENGTH,
                Constants.SETTING_KEY_INSIGHTS_BATCH_SIZE,
            ):
                try:
                    data[setting.key] = int(setting.value)
                except (TypeError, ValueError):
                    if setting.key == "refresh_onboarding_cadence_days":
                        data[setting.key] = Setting.get_refresh_onboarding_cadence_days()
                    elif setting.key == Constants.SETTING_KEY_RUN_SUMMARY_MAX_LENGTH:
                        data[setting.key] = Setting.get_run_summary_max_length()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_POOL_CAP:
                        data[setting.key] = Setting.get_insights_pool_cap()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_SHOWN_COUNT:
                        data[setting.key] = Setting.get_insights_shown_count()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_RECENT_RUNS:
                        data[setting.key] = Setting.get_insights_recent_runs()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_MIN_POOL_BEFORE_SHUFFLE:
                        data[setting.key] = Setting.get_insights_min_pool_before_shuffle()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_MAX_LENGTH:
                        data[setting.key] = Setting.get_insights_max_length()
                    elif setting.key == Constants.SETTING_KEY_INSIGHTS_BATCH_SIZE:
                        data[setting.key] = Setting.get_insights_batch_size()
                    else:
                        data[setting.key] = Setting.get_observations_max_length()

        defaults = {
            "refresh_onboarding_cadence_days": Setting.get_refresh_onboarding_cadence_days(),
            "observations_enabled": Setting.get_observations_enabled(),
            "observations_max_length": Setting.get_observations_max_length(),
            "insights_enabled": Setting.get_insights_enabled(),
            "insights_pool_cap": Setting.get_insights_pool_cap(),
            "insights_shown_count": Setting.get_insights_shown_count(),
            "insights_recent_runs": Setting.get_insights_recent_runs(),
            "insights_min_pool_before_shuffle": Setting.get_insights_min_pool_before_shuffle(),
            "insights_max_length": Setting.get_insights_max_length(),
            "insights_batch_size": Setting.get_insights_batch_size(),
            "knowledge_min_confidence": Setting.get_knowledge_min_confidence(),
            "history_max_turns": Setting.get_history_max_turns(),
            "session_inactivity_minutes": Setting.get_session_inactivity_minutes(),
            "thin_answer_min_words": Setting.get_thin_answer_min_words(),
            "generic_answers_default": Setting.get_generic_answers_default(),
            "chat_openers": Setting.get_chat_openers(),
            "risk_keywords": Setting.get_risk_keywords(),
            "trust_and_safety_email": Setting.get_trust_and_safety_email(),
            "store_turn_prompts": Setting.get_store_turn_prompts(),
            "chat_debug_enabled": Setting.get_chat_debug_enabled(),
            "ai_retrieval_enabled": Setting.get_ai_retrieval_enabled(),
            "ai_retrieval_exercise_enabled": Setting.get_ai_retrieval_exercise_enabled(),
            "update_summary": Setting.get_update_summary(),
            "update_exercise_summary": Setting.get_update_exercise_summary(),
            "reply_length": Setting.get_reply_length_instruction(),
            "one_question": Setting.get_one_question_instruction(),
            "client_knowledge_rule": Setting.get_client_knowledge_rule(),
            "onboarding_followup_permission_ask": Setting.get_onboarding_followup_permission_ask(),
            "onboarding_followup_decline": Setting.get_onboarding_followup_decline(),
            "onboarding_followup_reask": Setting.get_onboarding_followup_reask(),
            "onboarding_followup_chip_yes": Setting.get_onboarding_followup_chip_yes(),
            "onboarding_followup_chip_no": Setting.get_onboarding_followup_chip_no(),
            "run_summary_prompt": Setting.get_run_summary_prompt(),
            "run_summary_tone_guide": Setting.get_run_summary_tone_guide(),
            "run_summary_max_length": Setting.get_run_summary_max_length(),
        }
        for key, value in defaults.items():
            data.setdefault(key, value)

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):

        serializer = SettingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.save()

        return Response(data, status=status.HTTP_200_OK)
