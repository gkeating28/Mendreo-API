from rest_framework import status
from rest_framework.response import Response

from ..user.models import UserSettings
from ..utils.Permissions import IsAdminPermission, IsConsumerPermission
from ..utils.Views import SmartAPIView
from .defaults import STEP_IDS
from .serializers import TourAudioSerializer, TourConfigSerializer
from .services import TourSpeechError, admin_steps, consumer_steps, generate_step_audio, save_step_text


class Tour(SmartAPIView):
    """GET /tour. Merged steps for the signed-in person."""

    permission_classes = [IsConsumerPermission]

    def get(self, request):
        return Response({"steps": consumer_steps()}, status=status.HTTP_200_OK)


class TourConfig(SmartAPIView):
    """GET and PUT /tour/config. Admin copy, plus whether each clip is stale."""

    permission_classes = [IsAdminPermission]

    def get(self, request):
        return Response({"steps": admin_steps()}, status=status.HTTP_200_OK)

    def put(self, request):
        serializer = TourConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        save_step_text(serializer.validated_data["steps"])
        return Response({"steps": admin_steps()}, status=status.HTTP_200_OK)


class TourStepAudio(SmartAPIView):
    """POST /tour/steps/<step_id>/audio. Generate and store the step's clip."""

    permission_classes = [IsAdminPermission]

    def post(self, request, step_id):
        if step_id not in STEP_IDS:
            return self.not_found("Step not found")
        serializer = TourAudioSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        voice_id = (
            serializer.validated_data.get("voice_id")
            or UserSettings.VoiceId.FEMALE_IRISH
        )
        try:
            step = generate_step_audio(step_id, voice_id)
        except TourSpeechError as exc:
            return Response({"detail": exc.detail}, status=exc.status_code)
        return Response(step, status=status.HTTP_200_OK)
