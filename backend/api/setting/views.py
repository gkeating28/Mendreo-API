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

            if setting.key == "survey_enabled":
                data[setting.key] = setting.value.lower() == "true"

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):

        serializer = SettingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.save()

        return Response(data, status=status.HTTP_200_OK)
