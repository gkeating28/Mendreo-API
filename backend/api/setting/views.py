from __future__ import unicode_literals

from rest_framework import status
from rest_framework.response import Response

from .models import Setting

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
            "observations_instruction": Setting.get_observations_instruction(),
            "observations_tone_guide": Setting.get_observations_tone_guide(),
            "observations_max_length": Setting.get_observations_max_length(),
        }
        for key, value in defaults.items():
            data.setdefault(key, value)

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):

        serializer = SettingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.save()

        return Response(data, status=status.HTTP_200_OK)
