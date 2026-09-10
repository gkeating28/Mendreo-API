"""ElevenLabs server-to-server endpoints (Custom LLM + post-call webhook)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import require_elevenlabs_llm_secret
from ..voice.services import (
    extract_conversation_id,
    extract_grant_token,
    extra_body_from_request,
    iter_completion_sse,
    iter_silent_completion_sse,
    latest_user_text,
    reconcile_post_call_transcript,
    resolve_usable_grant,
    stamp_conversation_id,
    usable_voice_user_text,
)
from ..voice.webhook_auth import ElevenLabsWebhookError, construct_event

logger = logging.getLogger(__name__)


class ElevenLabsChatCompletions(APIView):
    """
    OpenAI-compatible Custom LLM endpoint.

    Identity comes from VoiceGrant in elevenlabs_extra_body.grant — never from
    a client-supplied user_id. Gemini runs inline (Railway worker), not Celery.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        try:
            require_elevenlabs_llm_secret(request)
        except PermissionDenied as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_403_FORBIDDEN)

        data = request.data if isinstance(request.data, dict) else {}

        try:
            grant = resolve_usable_grant(extract_grant_token(data))
            grant = stamp_conversation_id(grant, extract_conversation_id(data))
        except PermissionDenied as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        user_text = usable_voice_user_text(latest_user_text(data.get("messages")))
        if not user_text:
            response = StreamingHttpResponse(
                iter_silent_completion_sse(),
                content_type="text/event-stream",
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

        # Explicitly ignore extra_body user/consumer ids — they are not trusted.
        extra = extra_body_from_request(data)
        extra.pop("user_id", None)
        extra.pop("consumer_id", None)
        data.pop("user", None)
        data.pop("user_id", None)
        data.pop("consumer_id", None)

        response = StreamingHttpResponse(
            iter_completion_sse(grant, user_text),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class ElevenLabsPostCallWebhook(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        raw = request.body
        signature = request.headers.get("ElevenLabs-Signature") or request.headers.get(
            "elevenlabs-signature"
        )
        try:
            event = construct_event(raw, signature, settings.ELEVENLABS_WEBHOOK_SECRET)
        except ElevenLabsWebhookError as exc:
            return Response({"detail": exc.detail}, status=status.HTTP_401_UNAUTHORIZED)

        event_type = event.get("type") or event.get("event_type")
        if event_type and event_type != "post_call_transcription":
            return Response({"status": "ignored", "type": event_type}, status=status.HTTP_200_OK)

        payload = event.get("data") if isinstance(event.get("data"), dict) else event
        conversation_id = (
            payload.get("conversation_id")
            or event.get("conversation_id")
            or ""
        )
        transcript = payload.get("transcript") or []
        result = reconcile_post_call_transcript(
            conversation_id=str(conversation_id) if conversation_id else "",
            transcript=transcript,
            payload=payload,
        )
        return Response(result, status=status.HTTP_200_OK)
