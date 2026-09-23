from __future__ import unicode_literals

from django.conf import settings
from django.db import transaction

from .models import Message
from .serializers import MessageDetailSerializer, MessageCreateSerializer, MessageListSerializer
from ..utils import QueryParams
from ..utils.AIWorkerClient import enqueue_agent_response, request_agent_response
from ..utils.ExerciseOffer import maybe_handle_offer_response
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
        data = dict(data)
        if getattr(request, "_ai_pending", False):
            data["ai_pending"] = True
        if getattr(request, "_session_state", None) is not None:
            data["session_state"] = request._session_state
        elif settings.AI_STATE_MACHINE_ENABLED:
            from ..utils.SessionStateMachine import build_session_state

            data["session_state"] = build_session_state(instance.session)
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

        from_suggested_response = _from_suggested_response(request.data)

        if settings.AI_STATE_MACHINE_ENABLED:
            from ..utils.SessionStateMachine import (
                consume_chip,
                leave_awaiting_on_typed_text,
            )

            outcome = consume_chip(instance, from_suggested_response)
            if outcome is not None:
                instance = outcome.message
                request._session_state = outcome.session_state
            else:
                if not from_suggested_response:
                    leave_awaiting_on_typed_text(instance)
                if settings.AI_ASYNC_MESSAGES:
                    enqueue_agent_response(instance)
                    request._ai_pending = True
                else:
                    instance = request_agent_response(
                        user_message=instance, session=instance.session
                    )
                    instance.session.refresh_from_db()
        else:
            offer_reply = maybe_handle_offer_response(instance, from_suggested_response)
            if offer_reply is not None:
                instance = offer_reply
            elif settings.AI_ASYNC_MESSAGES:
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


def _from_suggested_response(data) -> bool:
    if not data:
        return False
    value = data.get("from_suggested_response")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)
