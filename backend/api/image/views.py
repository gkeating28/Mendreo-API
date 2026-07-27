from __future__ import unicode_literals

from .models import Image

from rest_framework import status
from rest_framework.response import Response

from .serializers import (
    ImageUploadSerializer,
    ImageDetailSerializer,
    ImageUploadEditSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import File, Body

from ..utils.Views import SmartAPIView, SmartDetailAPIView


class Create(SmartAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Image

    def post(self, request):
        data = self.inject_user(request, key="created_by")

        create_serializer = ImageUploadSerializer(data=data)
        create_serializer.is_valid(raise_exception=True)
        image = create_serializer.save()

        pre_signed_url, content_type = File.get_upload_link(image.original)

        data = {
            "pre_signed_url": pre_signed_url,
            "content_type": content_type,
            "image": ImageDetailSerializer(image).data
        }

        return Response(data, status=status.HTTP_201_CREATED)


class Edit(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Image
    edit_serializer = ImageUploadEditSerializer
    detail_serializer = ImageDetailSerializer

    partial = False

    def queryset(self, request, id):
        token = Body.get_str(request, "token", raise_exception=True)

        return Image.objects.filter(id=id, token=token, created_by=request.user)
