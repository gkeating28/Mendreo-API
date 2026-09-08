from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from .elevenlabs_client import ElevenLabsConfigError, ElevenLabsRequestError
from .services import mint_voice_token


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
