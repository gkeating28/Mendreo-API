"""GET /metrics for the signed-in consumer."""

from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from ..knowledge.models import KnowledgeField
from ..question.models import Question
from ..utils import DateUtils
from ..utils.Permissions import IsConsumerPermission
from ..utils.Views import SmartAPIView
from .models import SessionMetric


class Metrics(SmartAPIView):
    permission_classes = [IsConsumerPermission]

    def has_permission(self, request, method):
        return method == "GET"

    def get(self, request):
        consumer = self.get_consumer_from_request()
        queryset = SessionMetric.objects.filter(consumer=consumer).order_by("recorded_at")

        keys_param = (request.query_params.get("keys") or "").strip()
        keys = []
        if keys_param:
            keys = [key.strip() for key in keys_param.split(",") if key.strip()]
            queryset = queryset.filter(key__in=keys)

        try:
            start = _bound(request.query_params.get("from"), end=False)
            end = _bound(request.query_params.get("to"), end=True)
        except ValueError:
            raise ValidationError({"detail": "Invalid date format. Use YYYY-MM-DD."})

        if start is not None:
            queryset = queryset.filter(recorded_at__gte=start)
        if end is not None:
            queryset = queryset.filter(recorded_at__lt=end)

        rows = list(queryset)
        order = keys or []
        if not keys:
            for row in rows:
                if row.key not in order:
                    order.append(row.key)

        labels = _labels(order)
        grouped = {key: [] for key in order}
        for row in rows:
            grouped.setdefault(row.key, []).append(
                {
                    "recorded_at": row.recorded_at.isoformat(),
                    "value": float(row.value),
                    "exercise_id": row.exercise_id,
                }
            )

        payload = [
            {
                "key": key,
                "label": labels.get(key) or key,
                "points": grouped.get(key, []),
            }
            for key in order
        ]
        return Response(payload, status=status.HTTP_200_OK)


def _bound(value, *, end: bool):
    if value is None or str(value).strip() == "":
        return None
    day = DateUtils.parse_date(str(value).strip())
    range_start, range_end = DateUtils.progress_day_bounds(day, day)
    return range_end if end else range_start


def _labels(keys) -> dict:
    labels = {}
    if not keys:
        return labels
    for field in KnowledgeField.objects.filter(key__in=keys):
        labels[field.key] = field.label
    missing = [key for key in keys if key not in labels]
    if missing:
        for question in Question.objects.filter(key__in=missing).order_by("created_at"):
            labels.setdefault(question.key, question.title)
    return labels
