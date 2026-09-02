from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..session.models import Session
from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from .models import SUMMARY_STEP_ID, ExerciseReflection
from .services import completed_runs_queryset, serialize_run


def _page_params(request):
    try:
        page = max(1, int(request.query_params.get("page") or 1))
        page_size = min(50, max(1, int(request.query_params.get("page_size") or 25)))
    except (TypeError, ValueError):
        raise ValidationError({"detail": "page and page_size must be integers."})
    return page, page_size


class RunList(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def has_permission(self, request, method):
        return method == "GET"

    def get(self, request):
        consumer = self.get_consumer_from_request()
        status_filter = (request.query_params.get("status") or "completed").lower()
        if status_filter != "completed":
            return Response(
                {"detail": "Only status=completed is supported."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        queryset = completed_runs_queryset(consumer)
        page, page_size = _page_params(request)
        count = queryset.count()
        start = (page - 1) * page_size
        rows = list(queryset[start : start + page_size])
        return Response(
            {
                "count": count,
                "results": [serialize_run(session, include_transcript=False) for session in rows],
            },
            status=status.HTTP_200_OK,
        )


class RunDetail(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def has_permission(self, request, method):
        return method == "GET"

    def get(self, request, id):
        consumer = self.get_consumer_from_request()
        session = completed_runs_queryset(consumer, include_messages=True).filter(id=id).first()
        if not session:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_run(session, include_transcript=True), status=status.HTTP_200_OK)


class RunReflection(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def has_permission(self, request, method):
        return method in ("PUT", "PATCH")

    def put(self, request, id, step_id):
        return self._upsert(request, id, step_id)

    def patch(self, request, id, step_id):
        return self._upsert(request, id, step_id)

    def _upsert(self, request, id, step_id):
        consumer = self.get_consumer_from_request()
        session = Session.objects.filter(
            id=id,
            consumer=consumer,
            completed=True,
            abandoned=False,
            exercise__isnull=False,
        ).first()
        if not session:
            return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

        text = ""
        if isinstance(request.data, dict):
            text = str(request.data.get("text") or "")
        text = text.strip()
        key = (step_id or "").strip() or SUMMARY_STEP_ID

        existing = ExerciseReflection.objects.filter(session=session, step_id=key).first()
        if not text:
            if existing:
                existing.delete()
            return Response({"stepId": key, "text": "", "updatedAt": None}, status=status.HTTP_200_OK)

        if existing:
            existing.text = text
            existing.save(update_fields=["text", "updated_at"])
            row = existing
        else:
            row = ExerciseReflection.objects.create(
                session=session,
                consumer=consumer,
                step_id=key,
                text=text,
            )
        return Response(
            {
                "stepId": row.step_id,
                "text": row.text,
                "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
            },
            status=status.HTTP_200_OK,
        )
