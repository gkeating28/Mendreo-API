from __future__ import unicode_literals

from django.db import transaction

from .models import Message
from .serializers import MessageDetailSerializer, MessageCreateSerializer, MessageListSerializer
from ..utils import QueryParams
from ..utils.AIWorkerClient import request_agent_response
from ..utils.Permissions import (
    IsConsumerPermission, IsAdminPermission,
)
from ..utils.Views import SmartPaginationAPIView


class ListCreate(SmartPaginationAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Message
    detail_serializer = MessageDetailSerializer
    create_serializer = MessageCreateSerializer
    list_serializer = MessageListSerializer

    def add_filters(self, queryset, request):
        session_id = QueryParams.get_str(request, "session_id")
        consumer_id = QueryParams.get_str(request, "consumer_id")

        if self.is_consumer_request():
            consumer_id = self.get_consumer_from_request().user.id

        if session_id:
            queryset = queryset.filter(session_id=session_id)

        if consumer_id:
            queryset = queryset.filter(session__consumer_id=consumer_id)

        return queryset

    def override_post_data(self, request, data):

        data['consumer'] = self.get_consumer_from_request().user_id

        return data

    def post(self, request):
        """Create the user message, commit, then ask the AI worker.

        Parent SmartPaginationAPIView.post is @transaction.atomic for the whole
        request. The hybrid worker uses a separate DB connection, so it must
        only be called after the message row is committed.
        """
        if not self.has_permission(request, "POST") or not self.has_role_permission("POST", self.model):
            return self.get_permission_denied_response(request, "POST")

        if not self.get_create_serializer(request):
            return self.get_missing_serializer_response(request, "POST")

        create_serializer_class = self.get_create_serializer(request)

        data = request.data

        if hasattr(self.request.data, "_mutable"):
            self.request.data._mutable = True

        data = self.override_post_data(request, data)

        if hasattr(self.request.data, "_mutable"):
            self.request.data._mutable = False

        with transaction.atomic():
            create_serializer = create_serializer_class(data=data)
            create_serializer.is_valid(raise_exception=True)
            instance = create_serializer.save()

        # Transaction has committed — Railway can see user_message_id now.
        instance = request_agent_response(user_message=instance, session=instance.session)

        detail_serializer_class = self.get_detail_serializer(request, instance)
        data = detail_serializer_class(instance).data

        return self.post_response(request, instance, data)
