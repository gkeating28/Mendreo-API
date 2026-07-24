from __future__ import unicode_literals

from .models import Package

from .serializers import (
    PackageListSerializer,
    PackageDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import QueryParams, Constants

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):

    model = Package
    list_serializer = PackageListSerializer

    permission_classes = [IsConsumerPermission | IsAdminPermission]

    def add_filters(self, queryset, request):
        frequency = QueryParams.get_enum(request, "frequency", Constants.FREQUENCIES)

        # default package is created only on api side, UI isn't supposed to know about it
        queryset = queryset.exclude(default=True)

        if frequency:
            queryset = queryset.filter(price__frequency=frequency)

        return queryset.distinct()

    def has_permission(self, request, method):
        return method == "GET"


class Detail(SmartDetailAPIView):
    permission_classes = [IsConsumerPermission | IsAdminPermission]

    model = Package
    detail_serializer = PackageDetailSerializer

    def queryset(self, request, id):
        # default package is created only on api side, UI isn't supposed to know about it
        return Package.objects.filter(id=id).exclude(default=True)
