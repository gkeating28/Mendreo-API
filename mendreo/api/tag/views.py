from __future__ import unicode_literals

from .models import Tag

from .serializers import (
    TagListSerializer,
    TagCreateSerializer,
    TagDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission
)

from ..utils import QueryParams
from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):

    model = Tag
    list_serializer = TagListSerializer
    create_serializer = TagCreateSerializer
    detail_serializer = TagDetailSerializer

    permission_classes = [IsAdminPermission]

    def add_filters(self, query, request):
        search_term = QueryParams.get_str(request, "search_term")

        if search_term:
            query = query.filter(name__icontains=search_term)

        return query


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission]

    model = Tag
    detail_serializer = TagDetailSerializer

    deletable = True

