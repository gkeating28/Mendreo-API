from __future__ import unicode_literals

from .serializers import AICreateSerializer
from ..post.serializers import Post, PostDetailSerializer

from ..utils.Permissions import (
    IsAdminPermission,
)

from ..utils.Views import SmartPaginationAPIView


class Create(SmartPaginationAPIView):

    model = Post
    create_serializer = AICreateSerializer
    detail_serializer = PostDetailSerializer

    permission_classes = [IsAdminPermission]

