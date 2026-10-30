from __future__ import unicode_literals

from django.conf import settings
from django.db import transaction
from rest_framework.response import Response

from .models import Message
from .serializers import MessageDetailSerializer, MessageCreateSerializer, MessageListSerializer
from ..utils import QueryParams
from ..utils.AIWorkerClient import enqueue_agent_response, request_agent_response
from ..utils.ExerciseOffer import maybe_handle_offer_response
from ..utils.Permissions import (
    IsConsumerPermission, IsAdminPermission,
)
from ..utils.Views import SmartAPIView, SmartPaginationAPIView


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
        else:
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

        from ..utils.SessionStateMachine import (
            confirm_readiness_reply,
            confirm_summary_if_done,
            consume_chip,
            handle_typed_while_awaiting,
        )

        outcome = consume_chip(instance, from_suggested_response)
        if outcome is None and not from_suggested_response:
            outcome = handle_typed_while_awaiting(instance)
        if outcome is None:
            outcome = confirm_readiness_reply(instance)
        if outcome is None and not from_suggested_response:
            outcome = confirm_summary_if_done(instance)
        if outcome is not None:
            instance = outcome.message
            request._session_state = outcome.session_state
        elif settings.AI_ASYNC_MESSAGES:
            enqueue_agent_response(instance)
            request._ai_pending = True
        else:
            instance = request_agent_response(
                user_message=instance, session=instance.session
            )
            instance.session.refresh_from_db()

        detail_serializer_class = self.get_detail_serializer(request, instance)
        data = detail_serializer_class(instance).data
        data = self.override_response_data(request, data, instance)

        return self.post_response(request, instance, data)


_DEBUG_SECTIONS = (
    "THERAPEUTIC_INSTRUCTIONS",
    "PROGRAMMING_INSTRUCTIONS",
    "EXERCISES",
    "GOALS",
    "TRIAGE",
    "SESSION_CONTEXT",
    "KNOWLEDGE",
    "ONBOARDING_FOLLOW_UP",
    "CLIENT_SUMMARY",
    "DATE",
    "PENDING_QUESTION",
)
_DEBUG_USER_SECTIONS = ("RETRIEVED", "TURN_HINT")


def _tags_present(text, tags):
    body = text or ""
    return [tag for tag in tags if f"<{tag}>" in body]


def _is_assistant_message(message) -> bool:
    sender = message.sender
    return bool(getattr(sender, "agent_id", None)) and not getattr(sender, "consumer_id", None)


def _retrieved_sources(message):
    from ..grounding.models import KnowledgeSource

    source_ids = []
    for item in message.retrieval or []:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        if not source_id or source_id in source_ids:
            continue
        source_ids.append(source_id)
    titles = dict(
        KnowledgeSource.objects.filter(id__in=source_ids).values_list("id", "title")
    )
    return [
        {"id": source_id, "title": titles.get(source_id, source_id)}
        for source_id in source_ids
    ]


def _step_decision(message):
    usage = message.usage if isinstance(message.usage, dict) else {}
    decision = usage.get("step_decision")
    return decision if isinstance(decision, dict) else None


class MessageDebug(SmartAPIView):
    """Test-only read of the prompt stored for one assistant reply."""

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    def get(self, request, id):
        from ..setting.models import Setting

        if not Setting.get_chat_debug_enabled():
            return self.not_found()

        message = (
            Message.objects.filter(id=id)
            .select_related("sender", "session")
            .first()
        )
        if message is None or not _is_assistant_message(message):
            return self.not_found()
        if self.is_consumer_request():
            consumer = self.get_consumer_from_request()
            if message.session.consumer_id != consumer.user_id:
                return self.not_found()

        from .models import TurnPrompt

        prompt = TurnPrompt.objects.filter(message=message).first()
        if prompt is None:
            return self.not_found(
                "No stored prompt for this message. Replies are only stored while chat debug is on."
            )

        meta = message.session.cached_prompt_meta or {}
        history = prompt.history or []
        return Response(
            {
                "message_id": message.id,
                "model_name": prompt.model_name,
                "retrieval_enabled": bool(meta.get("retrieval_enabled")),
                "sections": _tags_present(prompt.system_prompt, _DEBUG_SECTIONS),
                "user_prompt_sections": {
                    tag: f"<{tag}>" in (prompt.user_prompt or "")
                    for tag in _DEBUG_USER_SECTIONS
                },
                "retrieved_sources": _retrieved_sources(message),
                "history_turns": len(history) if isinstance(history, list) else 0,
                "system_prompt": prompt.system_prompt,
                "user_prompt": prompt.user_prompt,
                "step_decision": _step_decision(message),
            }
        )


class MessagePrompt(SmartAPIView):
    """Admin read of the prompt stored for one assistant message."""

    permission_classes = [IsAdminPermission]

    def get(self, request, id):
        message = Message.objects.filter(id=id).first()
        if message is None:
            return self.not_found()
        from .models import TurnPrompt

        prompt = TurnPrompt.objects.filter(message=message).first()
        if prompt is None:
            return self.not_found("No stored prompt for this message.")
        return Response(
            {
                "message_id": message.id,
                "session_id": message.session_id,
                "model_name": prompt.model_name,
                "system_prompt": prompt.system_prompt,
                "user_prompt": prompt.user_prompt,
                "history": prompt.history or [],
                "created_at": prompt.created_at,
            }
        )


def _from_suggested_response(data) -> bool:
    if not data:
        return False
    value = data.get("from_suggested_response")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return bool(value)
