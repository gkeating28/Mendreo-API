from .models import Feedback
from .serializers import (
    FeedbackCreateSerializer,
    FeedbackDetailSerializer,
    FeedbackListSerializer,
    FeedbackUserCreateSerializer
)

from ..utils.Permissions import IsAdminPermission, IsConsumerPermission
from ..utils.Views import SmartPaginationAPIView


class Create(SmartPaginationAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Feedback
    create_serializer = FeedbackCreateSerializer
    detail_serializer = FeedbackDetailSerializer
    list_serializer = FeedbackListSerializer

    def add_filters(self, queryset, request):

        queryset = queryset.filter(user__isnull=False)

        return queryset

    def get_create_serializer(self, request):
        if self.is_consumer_request():
            return FeedbackUserCreateSerializer

        return FeedbackCreateSerializer

    def has_permission(self, request, method):
        if method == "POST":
            return True

        return self.is_admin_request()

    def override_post_data(self, request, data):
        if self.is_consumer_request():
            data["user"] = request.user.id

        return data
