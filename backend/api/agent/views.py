from __future__ import unicode_literals

from .models import Agent

from .serializers import (
    AgentCreateSerializer,
    AgentEditSerializer,
    AgentListSerializer,
    AgentDetailSerializer,
    AgentAdminListSerializer,
    AgentAdminDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import QueryParams

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):

    model = Agent
    list_serializer = AgentListSerializer
    detail_serializer = AgentDetailSerializer
    create_serializer = AgentCreateSerializer

    admin_list_serializer = AgentAdminListSerializer
    admin_detail_serializer = AgentAdminDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    def add_filters(self, query, request):
        search_term = QueryParams.get_str(request, "search_term")

        if search_term:
            query = query.filter(name__icontains=search_term)

        return query

    def override_post_data(self, request, data):
        self.inject_user(request, "created_by")
        return data

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Agent
    edit_serializer = AgentEditSerializer
    detail_serializer = AgentDetailSerializer

    admin_detail_serializer = AgentAdminDetailSerializer

    deletable = True

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()
