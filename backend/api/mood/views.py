from .models import MoodEntry
from .serializers import (
    MoodEntryCreateSerializer,
    MoodEntryDetailSerializer,
    MoodEntryEditSerializer,
    MoodEntryListSerializer,
)
from ..utils import QueryParams
from ..utils.Permissions import IsAdminPermission, IsConsumerPermission
from ..utils.Views import SmartDetailAPIView, SmartPaginationAPIView


class ListCreate(SmartPaginationAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = MoodEntry
    list_serializer = MoodEntryListSerializer
    detail_serializer = MoodEntryDetailSerializer
    create_serializer = MoodEntryCreateSerializer
    allow_disable_pagination = True

    def add_filters(self, queryset, request):
        consumer_id = QueryParams.get_str(request, "consumer_id")
        mood_score = QueryParams.get_int(request, "mood_score")
        date_from = QueryParams.get_date(request, "from")
        date_to = QueryParams.get_date(request, "to")

        if self.is_consumer_request():
            consumer_id = self.get_consumer_from_request().user_id

        if consumer_id:
            queryset = queryset.filter(consumer_id=consumer_id)

        if mood_score is not None:
            queryset = queryset.filter(mood_score=mood_score)

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset.order_by("-created_at")

    def override_post_data(self, request, data):
        if self.is_consumer_request():
            data["consumer"] = self.get_consumer_from_request().user_id
        return data

    def has_permission(self, request, method):
        if method == "GET":
            return True
        if method == "POST":
            # Consumers create their own entries; admins may create on behalf of a consumer.
            return True
        return False


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = MoodEntry
    edit_serializer = MoodEntryEditSerializer
    detail_serializer = MoodEntryDetailSerializer
    deletable = True

    def add_filters(self, queryset, request):
        if self.is_consumer_request():
            queryset = queryset.filter(consumer=self.get_consumer_from_request())
        return queryset

    def has_permission(self, request, method):
        return method in ("GET", "PATCH", "DELETE")
