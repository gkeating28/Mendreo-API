import shortuuid

from .models import File

from .serializers import FileDetailSerializer, FileUploadSerializer, FileEditSerializer

from ..utils.Views import SmartAPIView, SmartDetailAPIView

from rest_framework import status
from rest_framework.response import Response

from ..utils import File as FileUtils, Body

from ..utils.Permissions import (
    IsAdminPermission,
)


class Create(SmartAPIView):
    permission_classes = [IsAdminPermission]

    model = File

    def post(self, request):
        self.inject_user(request, "created_by")
        data = request.data

        create_serializer = FileUploadSerializer(data=data)
        create_serializer.is_valid(raise_exception=True)
        file = create_serializer.save()

        pre_signed_url = FileUtils.get_upload_link(file.url[1:])
        file.token = shortuuid.uuid()
        file.save()

        parts = file.url.partition("/files/")
        filename = parts[2]

        data = {
            "pre_signed_url": pre_signed_url,
            "file": FileDetailSerializer(file).data,
            "filename": filename,
        }

        return Response(data, status=status.HTTP_201_CREATED)


class Edit(SmartDetailAPIView):
    permission_classes = [IsAdminPermission]

    model = File
    edit_serializer = FileEditSerializer
    detail_serializer = FileDetailSerializer

    partial = False

    def queryset(self, request, id):
        token = Body.get_str(request, "token", raise_exception=True)

        return File.objects.filter(id=id, token=token, created_by=request.user)
