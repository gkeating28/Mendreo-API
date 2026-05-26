from __future__ import unicode_literals

from .models import Asset
from .serializers import (
    AssetListSerializer,
    AssetCreateSerializer,
    AssetDetailSerializer,
    AssetEditSerializer
)
from ..utils.Permissions import IsAdminPermission, IsConsumerPermission
from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):

    model = Asset
    list_serializer = AssetListSerializer
    create_serializer = AssetCreateSerializer
    detail_serializer = AssetDetailSerializer


class Detail(SmartDetailAPIView):

    model = Asset
    detail_serializer = AssetDetailSerializer
    edit_serializer = AssetEditSerializer

    permission_classes = [IsConsumerPermission | IsAdminPermission]

    deletable = True

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()
