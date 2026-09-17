from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from .elevenlabs_client import ElevenLabsConfigError, ElevenLabsRequestError
from .services import (
    mint_voice_token,
    synthesize_agent_message,
    synthesize_spoken_text,
    synthesize_voice_preview,
)


class VoiceToken(SmartAPIView):
    """Mint an ElevenLabs conversation credential + opaque VoiceGrant."""

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        session_id = request.data.get("session_id") or None
        if session_id is not None:
            session_id = str(session_id).strip() or None

        try:
            payload = mint_voice_token(consumer, session_id)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except ElevenLabsConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ElevenLabsRequestError as exc:
            return Response(
                {"detail": str(exc)},
                status=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            )

        return Response(payload, status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "POST"


class VoiceTts(SmartAPIView):
    """Read-aloud for one existing agent message via ElevenLabs TTS.

    Distinct from Conversational AI (`POST /voice/token`). The API key never
    leaves the server. Playback stop is client-side (abort + pause).
    """

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        message_id = request.data.get("message_id") or None
        if message_id is not None:
            message_id = str(message_id).strip() or None
        raw_text = request.data.get("text")
        text = raw_text.strip() if isinstance(raw_text, str) else None
        voice_id = request.data.get("voice_id") or None
        if voice_id is not None:
            voice_id = str(voice_id).strip() or None

        try:
            if message_id:
                audio, content_type = synthesize_agent_message(consumer, message_id)
            elif text:
                audio, content_type = synthesize_spoken_text(consumer, text, voice_id)
            else:
                raise ValidationError({"message_id": "This field is required."})
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except ElevenLabsConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ElevenLabsRequestError as exc:
            return Response(
                {"detail": str(exc)},
                status=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            )

        return _audio_response(audio, content_type, filename="message.mp3")

    def has_permission(self, request, method):
        return method == "POST"


class VoicePreview(SmartAPIView):
    """Short Toni sample for a voice option. Does not save UserSettings."""

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        voice_id = request.data.get("voice_id") or None
        if voice_id is not None:
            voice_id = str(voice_id).strip() or None

        try:
            audio, content_type = synthesize_voice_preview(consumer, voice_id)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        except ElevenLabsConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ElevenLabsRequestError as exc:
            return Response(
                {"detail": str(exc)},
                status=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            )

        return _audio_response(audio, content_type, filename="preview.mp3")

    def has_permission(self, request, method):
        return method == "POST"


def _audio_response(audio: bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(audio, content_type=content_type)
    response["Cache-Control"] = "no-store"
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
