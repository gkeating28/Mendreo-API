from __future__ import unicode_literals

from rest_framework import status

from .models import Admin

from .serializers import (
    AdminCreateSerializer,
    AdminEditSerializer,
    AdminListSerializer,
    AdminDetailSerializer
)

from ..utils.Permissions import (
    IsAdminPermission,
)

from ..utils import QueryParams, Constants, DateUtils

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):
    model = Admin
    list_serializer = AdminListSerializer
    detail_serializer = AdminDetailSerializer
    create_serializer = AdminCreateSerializer

    permission_classes = [IsAdminPermission]

    def add_filters(self, query, request):
        search_term = QueryParams.get_str(request, "search_term")

        if search_term:
            query = query.filter(user__full_name__icontains=search_term)

        return query


class Detail(SmartDetailAPIView):
    model = Admin
    detail_serializer = AdminDetailSerializer
    edit_serializer = AdminEditSerializer

    permission_classes = [IsAdminPermission]

    deletable = True

    def queryset(self, request, id):
        return Admin.objects.filter(user_id=id)

    def handle_delete(self, instance):
        if instance.user_id == self.get_admin_from_request().user_id:
            return self.respond_with("You cannot delete your own account", status_code=status.HTTP_400_BAD_REQUEST)

        user = instance.user

        user.status = Constants.USER_STATUS_SUSPENDED
        user.deleted_at = DateUtils.now()
        user.save()

        return super(Detail, self).handle_delete(instance)
