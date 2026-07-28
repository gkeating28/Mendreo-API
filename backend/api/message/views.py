from __future__ import unicode_literals

from django.conf import settings
from django.db import transaction

from .models import Message
from .serializers import MessageDetailSerializer, MessageCreateSerializer, MessageListSerializer
from ..utils import QueryParams
from ..utils.AIWorkerClient import enqueue_agent_response, request_agent_response
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

    def override_response_data(self, request, data, instance):
        if getattr(request, "_ai_pending", False):
            data = dict(data)
            data["ai_pending"] = True
        return data

    def post(self, request):
        """Create the user message, then run or enqueue the AI reply.

        Parent SmartPaginationAPIView.post is @transaction.atomic for the whole
        request. The hybrid worker uses a separate DB connection, so AI work
        must only start after the message row is committed.
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

        # Transaction has committed — Railway / Celery can see user_message_id.
        if settings.AI_ASYNC_MESSAGES:
            enqueue_agent_response(instance)
            request._ai_pending = True
            # Return the user message immediately; clients poll GET /messages
            # (or session.last_message) for the agent reply.
        else:
            instance = request_agent_response(user_message=instance, session=instance.session)

        detail_serializer_class = self.get_detail_serializer(request, instance)
        data = detail_serializer_class(instance).data
        data = self.override_response_data(request, data, instance)

        return self.post_response(request, instance, data)
