from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
import time

from ..agent.models import Agent
from ..message.models import Message
from ..session.models import Session
from ..tasks import check_subscriptions
from ..utils.AIWorkerClient import _run_session_greeting
from ..utils.MessageFlow import apply_agent_response
from .auth import require_cron_secret, require_internal_secret


class MessageResponse(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        require_internal_secret(request)
        user_message_id = request.data.get("user_message_id")
        # Brief retries cover rare pooler visibility lag after Vercel commits.
        user_message = None
        for attempt in range(3):
            user_message = Message.objects.filter(id=user_message_id).first()
            if user_message:
                break
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
        if not user_message:
            return Response(
                {"detail": f"Message {user_message_id} not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        agent_message = Agent.get_response(user_message=user_message, session=user_message.session)
        apply_agent_response(user_message, agent_message)
        return Response({"agent_message_id": agent_message.id}, status=status.HTTP_200_OK)


class SessionGreeting(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        require_internal_secret(request)
        session = get_object_or_404(Session, id=request.data.get("session_id"))
        agent_message = _run_session_greeting(session)
        if not agent_message:
            return Response({"detail": "No greeting generated."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"agent_message_id": agent_message.id}, status=status.HTTP_200_OK)


class CheckSubscriptionsCron(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        require_cron_secret(request)
        check_subscriptions()
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
