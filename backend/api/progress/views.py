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
from .models import UserObservation
from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime


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


class Observation(_ProgressBase):
    def has_permission(self, request, method):
        return method == "PATCH"

    def patch(self, request, id):
        consumer = self.get_consumer_from_request()
        observation = UserObservation.objects.filter(consumer=consumer, id=id).first()
        if not observation:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        raw = request.data.get("dismissed_at")
        dismissed_at = parse_datetime(raw) if isinstance(raw, str) and raw else timezone.now()
        if dismissed_at is None:
            dismissed_at = timezone.now()
        observation.dismissed_at = dismissed_at
        observation.save(update_fields=["dismissed_at", "updated_at"])
        return Response(
            {
                "id": observation.id,
                "dismissed_at": observation.dismissed_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )


def _insight_source(item):
    run = item.source_run
    if run is None:
        return None
    exercise = run.exercise
    completed_at = run.completed_at.isoformat() if run.completed_at is not None else None
    return {
        "exercise_name": exercise.title if exercise is not None else None,
        "completed_at": completed_at,
    }


def _insights_payload(consumer, force_rotate):
    from ..setting.models import Setting
    from .insights import next_hand

    if not Setting.get_insights_enabled():
        return {
            "insights_enabled": False,
            "can_refresh": False,
            "insights": [],
        }
    hand = next_hand(consumer, force_rotate=force_rotate)
    return {
        "insights_enabled": True,
        "can_refresh": hand.can_refresh,
        "insights": [
            {
                "id": item.id,
                "text": item.text,
                "source_run_id": item.source_run_id,
                "source": _insight_source(item),
            }
            for item in hand.items
        ],
    }


def _open_insight_session(consumer, insight):
    """General chat whose first message is Toni saying the insight."""
    from ..message.models import Message
    from ..participant.models import Participant
    from ..session.models import Session

    with transaction.atomic():
        session = Session.create_general(consumer)
        if insight.source_run_id:
            session.source_run_id = insight.source_run_id
            session.save(update_fields=["source_run", "updated_at"])

        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(session=session, sender=agent, text=insight.text)
        session.last_message = message
        session.messages_no = 1
        session.agent_messages_no = 1
        session.save(
            update_fields=["last_message", "messages_no", "agent_messages_no", "updated_at"]
        )
        return session


class Insights(_ProgressBase):
    def get(self, request):
        consumer = self.get_consumer_from_request()
        return Response(_insights_payload(consumer, force_rotate=False), status=status.HTTP_200_OK)


class InsightsRefresh(_ProgressBase):
    def has_permission(self, request, method):
        return method == "POST"

    def post(self, request):
        consumer = self.get_consumer_from_request()
        return Response(_insights_payload(consumer, force_rotate=True), status=status.HTTP_200_OK)


class InsightsStart(_ProgressBase):
    def has_permission(self, request, method):
        return method == "POST"

    def post(self, request, id):
        from ..session.serializers import SessionDetailSerializer
        from ..setting.models import Setting
        from .models import UserInsight

        if not Setting.get_insights_enabled():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        consumer = self.get_consumer_from_request()
        insight = UserInsight.objects.filter(
            consumer=consumer,
            id=id,
            retired_at__isnull=True,
        ).first()
        if insight is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        session = _open_insight_session(consumer, insight)
        session = SessionDetailSerializer.optimise(
            type(session).objects.filter(id=session.id)
        ).first()
        return Response(
            SessionDetailSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )
