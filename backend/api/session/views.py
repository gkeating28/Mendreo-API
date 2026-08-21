from __future__ import unicode_literals

from django.db.models import Count
from django.db.models.functions import TruncDate

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.response import Response

from .models import Session
from .serializers import SessionDetailSerializer, SessionListSerializer

from ..exercise_summary.models import Exercise, ExerciseSummary

from ..utils import DateUtils, QueryParams
from ..utils.Permissions import (
    IsConsumerPermission,
    IsAdminPermission,
)
from ..utils.Views import SmartDetailAPIView, SmartAPIView, SmartPaginationAPIView


class List(SmartPaginationAPIView):

    model = Session
    list_serializer = SessionListSerializer
    detail_serializer = SessionDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]
    role_permission = True  

    def add_filters(self, queryset, request):
        # Internal AI-state blobs (100s of KB per session) — never serialized
        # for lists, so skip pulling them from the remote database entirely.
        queryset = queryset.defer("cached_prompt", "cached_history")

        exercise_id = QueryParams.get_str(request, "exercise_id")
        consumer_id = QueryParams.get_str(request, "consumer_id")
        risk_level = QueryParams.get_str(request, "risk_level")
        min_rating = QueryParams.get_float(request, "min_rating")
        max_rating = QueryParams.get_float(request, "max_rating")
        general = QueryParams.get_bool(request, "general")

        if self.is_consumer_request():
            consumer_id = self.get_consumer_from_request().user_id

        if consumer_id:
            queryset = queryset.filter(consumer_id=consumer_id)

        if exercise_id:
            queryset = queryset.filter(exercise_id=exercise_id)

        if general:
            queryset = queryset.filter(exercise__isnull=True)
            self.paginator.ordering = ["-updated_at", "-id"]
            queryset = queryset.order_by("-updated_at", "-id")

        if risk_level:
            queryset = queryset.filter(risk_level=risk_level)

        if min_rating is not None:
            queryset = queryset.filter(rating__gte=min_rating)

        if max_rating is not None:
            queryset = queryset.filter(rating__lte=max_rating)
        
        return queryset

    def post(self, request):
        if not self.has_permission(request, "POST"):
            return self.get_permission_denied_response(request, "POST")

        session = Session.create_general(self.get_consumer_from_request())
        session = SessionDetailSerializer.optimise(
            Session.objects.filter(id=session.id)
        ).first()
        data = SessionDetailSerializer(session).data
        return Response(data, status=status.HTTP_201_CREATED)

    def has_permission(self, request, method):
        if method == "POST":
            return self.is_consumer_request()
        return True


class Today(SmartAPIView):

    permission_classes = [IsConsumerPermission]
    
    def get(self, request):
        start, end = DateUtils.day_bounds()
        consumer = self.get_consumer_from_request()
        queryset = Session.objects.filter(
            created_at__gte=start,
            created_at__lt=end,
            consumer=consumer,
            exercise__isnull=True
        )
        queryset = SessionDetailSerializer.optimise(queryset)
        session = queryset.first()

        if not session:
            session = Session.get_or_create(consumer=consumer)
            # Re-fetch with optimised joins for the response payload.
            session = SessionDetailSerializer.optimise(
                Session.objects.filter(id=session.id)
            ).first()

        data = SessionDetailSerializer(session).data
        return Response(data=data, status=status.HTTP_200_OK)
    
    def has_permission(self, request, method):
        return method == "GET"


class Start(SmartAPIView):

    permission_classes = [IsConsumerPermission]

    def get(self, request):
        exercise_id = QueryParams.get_str(request, "exercise_id")
        exercise = None
        if exercise_id:
            exercise = Exercise.objects.get(id=exercise_id)

        consumer = self.get_consumer_from_request()

        session = Session.get_or_create(consumer=consumer, exercise=exercise)
        session = SessionDetailSerializer.optimise(
            Session.objects.filter(id=session.id)
        ).first()

        data = SessionDetailSerializer(session).data
        return Response(data=data, status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        if method == "GET":
            return True
        return False


class Detail(SmartDetailAPIView):

    model = Session
    detail_serializer = SessionDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]
    role_permission = True 

    def add_filters(self, queryset, request):
        
        if self.is_consumer_request():
            queryset = queryset.filter(consumer=self.get_consumer_from_request())
            
        return queryset


class CompletePreExercise(SmartAPIView):
    """Handoff: complete check-in and enter Step 1 (explicit Start exercise action)."""

    permission_classes = [IsConsumerPermission]
    model = Session

    def post(self, request, id):
        consumer = self.get_consumer_from_request()
        session = get_object_or_404(Session, id=id, consumer=consumer)

        if not session.in_pre_exercise_phase():
            return Response(
                {"detail": "Session is not in the pre-exercise check-in phase"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from ..exercise.pre_exercise import complete_pre_exercise_checkin

        summary = request.data.get("summary") if isinstance(request.data, dict) else None
        try:
            complete_pre_exercise_checkin(session, summary=summary)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        session = SessionDetailSerializer.optimise(
            Session.objects.filter(id=session.id)
        ).first()
        return Response(SessionDetailSerializer(session).data, status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "POST"


class Summary(SmartAPIView):
    model = Session
    detail_serializer = SessionDetailSerializer

    permission_classes = [IsConsumerPermission]

    def get(self, request, id):
        consumer = self.get_consumer_from_request()

        session = get_object_or_404(Session, id=id, consumer=consumer, completed=True, exercise__isnull=False)

        exercise_summary = ExerciseSummary.get_or_create(consumer, session.exercise)
        # exercise_summary.update(date=session.created_at)

        time_taken = session.last_message.created_at - session.created_at

        time_taken_in_seconds = time_taken.total_seconds()

        data = {
            "usage": get_usage(session, consumer),
            "observations": exercise_summary.observations,
            "time_taken_in_seconds": time_taken_in_seconds,
            "average_time_taken_in_seconds": session.exercise.average_duration,
        }

        return Response(data=data, status=status.HTTP_200_OK)


def get_usage(session, consumer):
    today = timezone.localdate()

    start_date = today - timedelta(days=9)  # 10 days including today
    range_start, _ = DateUtils.day_bounds(start_date)
    _, range_end = DateUtils.day_bounds(today)

    # Aggregate counts per day (timezone-aware); avoid created_at__date so
    # the (consumer, exercise, created_at) index can be used.
    counts_per_day = (
        Session.objects
        .filter(
            created_at__gte=range_start,
            created_at__lt=range_end,
            consumer=consumer,
            exercise=session.exercise
        )
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    counts_map = {row['day']: row['count'] for row in counts_per_day}
    days = [start_date + timedelta(days=i) for i in range(10)]
    return [{'date': d.isoformat(), 'count': counts_map.get(d, 0)} for d in days]
