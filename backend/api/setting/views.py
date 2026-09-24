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

            if setting.key in ("survey_enabled", "observations_enabled"):
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
            elif setting.key == Constants.SETTING_KEY_RISK_KEYWORDS:
                data[setting.key] = Setting.get_risk_keywords()
            elif setting.key in (
                "refresh_onboarding_cadence_days",
                "observations_max_length",
            ):
                try:
                    data[setting.key] = int(setting.value)
                except (TypeError, ValueError):
                    if setting.key == "refresh_onboarding_cadence_days":
                        data[setting.key] = Setting.get_refresh_onboarding_cadence_days()
                    else:
                        data[setting.key] = Setting.get_observations_max_length()

        defaults = {
            "refresh_onboarding_cadence_days": Setting.get_refresh_onboarding_cadence_days(),
            "observations_enabled": Setting.get_observations_enabled(),
            "observations_max_length": Setting.get_observations_max_length(),
            "knowledge_min_confidence": Setting.get_knowledge_min_confidence(),
            "history_max_turns": Setting.get_history_max_turns(),
            "session_inactivity_minutes": Setting.get_session_inactivity_minutes(),
            "thin_answer_min_words": Setting.get_thin_answer_min_words(),
            "generic_answers_default": Setting.get_generic_answers_default(),
            "risk_keywords": Setting.get_risk_keywords(),
            "trust_and_safety_email": Setting.get_trust_and_safety_email(),
        }
        for key, value in defaults.items():
            data.setdefault(key, value)

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):

        serializer = SettingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.save()

        return Response(data, status=status.HTTP_200_OK)
