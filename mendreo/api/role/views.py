from __future__ import unicode_literals
from django.db.models import Q
from rest_framework import status

from .models import Role

from .serializers import (
    RoleListSerializer,
    RoleDetailSerializer,
    RoleCreateSerializer,
    RoleEditSerializer
)

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView

from ..utils.Permissions import (
    IsAdminPermission
)

from ..utils import QueryParams


class ListCreate(SmartPaginationAPIView):

    model = Role
    list_serializer = RoleListSerializer
    detail_serializer = RoleDetailSerializer
    create_serializer = RoleCreateSerializer
    permission_classes = [IsAdminPermission]

    role_permission = True

    def add_filters(self, queryset, request):
        search_term = QueryParams.get_str(request, "search_term")

        if search_term:
            queryset = queryset.filter(name__icontains=search_term)

        queryset = RoleListSerializer.optimise(queryset)

        return queryset


class Detail(SmartDetailAPIView):

    model = Role
    detail_serializer = RoleDetailSerializer
    edit_serializer = RoleEditSerializer
    role_permission = True
    permission_classes = [IsAdminPermission]

    deletable = True

    def handle_delete(self, instance):
        if not instance.is_default:
            return super(Detail, self).handle_delete(instance)

        return self.respond_with("You cannot delete the default role", status_code=status.HTTP_400_BAD_REQUEST)
