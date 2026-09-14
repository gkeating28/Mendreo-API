from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .serializers import CheckInCreateSerializer
from .services import (
    CheckInAlreadySubmitted,
    get_check_in_progress,
    get_exercises_progress,
    get_mood_progress,
    get_patterns_progress,
    get_streaks,
    parse_date_range,
    submit_check_in,
)
from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView


class _ProgressBase(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def has_permission(self, request, method):
        return method == "GET"


class Mood(_ProgressBase):
    def get(self, request):
        try:
            start, end = parse_date_range(request)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        consumer = self.get_consumer_from_request()
        return Response(get_mood_progress(consumer, start, end), status=status.HTTP_200_OK)


class Exercises(_ProgressBase):
    def get(self, request):
        try:
            start, end = parse_date_range(request)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        consumer = self.get_consumer_from_request()
        return Response(
            get_exercises_progress(consumer, start, end), status=status.HTTP_200_OK
        )


class Patterns(_ProgressBase):
    def get(self, request):
        try:
            start, end = parse_date_range(request)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        consumer = self.get_consumer_from_request()
        return Response(
            get_patterns_progress(consumer, start, end), status=status.HTTP_200_OK
        )


class Streaks(_ProgressBase):
    def get(self, request):
        consumer = self.get_consumer_from_request()
        return Response(get_streaks(consumer), status=status.HTTP_200_OK)


class CheckIns(_ProgressBase):
    def has_permission(self, request, method):
        return method in ("GET", "POST")

    def get(self, request):
        try:
            start, end = parse_date_range(request)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
        consumer = self.get_consumer_from_request()
        return Response(get_check_in_progress(consumer, start, end), status=status.HTTP_200_OK)

    def post(self, request):
        serializer = CheckInCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        consumer = self.get_consumer_from_request()
        try:
            payload = submit_check_in(
                consumer,
                serializer.validated_data["anxiety"],
                serializer.validated_data["positive_emotion"],
            )
        except CheckInAlreadySubmitted:
            return Response(
                {"detail": "Check-in already submitted today."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(payload, status=status.HTTP_201_CREATED)
