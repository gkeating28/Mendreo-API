from __future__ import unicode_literals

from .models import ExerciseSummary
from .serializers import ExerciseSummaryDetailSerializer
from ..utils.Permissions import (
    IsAdminPermission,
)
from ..utils.Views import SmartDetailAPIView, SmartPaginationAPIView

from ..utils import QueryParams


class ListCreate(SmartPaginationAPIView):

    model = ExerciseSummary
    list_serializer = ExerciseSummaryDetailSerializer
    detail_serializer = ExerciseSummaryDetailSerializer

    permission_classes = [IsAdminPermission]

    def add_filters(self, query, request):
        consumer_id = QueryParams.get_str(request, "consumer_id")

        if consumer_id:
            query = query.filter(consumer_id=consumer_id)

        return query

    def has_permission(self, request, method):
        return method == "GET"


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission]

    model = ExerciseSummary
    detail_serializer = ExerciseSummaryDetailSerializer
