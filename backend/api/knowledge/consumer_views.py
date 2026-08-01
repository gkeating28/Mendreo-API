from __future__ import unicode_literals

from rest_framework import status
from rest_framework.response import Response

from .models import KnowledgeEntry, KnowledgeField
from .serializers import (
    KnowledgeActivitySerializer,
    KnowledgeEntryDetailSerializer,
    KnowledgeProfileEditSerializer,
)
from .services import (
    apply_sensitive_masking_to_entry_data,
    get_activity_queryset,
    get_field_history_queryset,
    get_knowledge_profile,
    write_knowledge_entry,
)
from ..consumer.models import Consumer
from ..utils import Constants, QueryParams
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView, SmartPaginationAPIView


def _get_consumer_or_404(view, consumer_id):
    consumer = Consumer.objects.filter(user_id=consumer_id).select_related("user").first()
    if not consumer:
        return None
    return consumer


class ConsumerKnowledgeProfile(SmartAPIView):
    """
    GET  /consumers/<id>/knowledge — profile grouped by category
    PATCH /consumers/<id>/knowledge — admin edit value(s) → append entries (source=admin)
    """

    permission_classes = [IsAdminPermission]
    role_permission = True
    model = KnowledgeEntry

    def get(self, request, id):
        if not self.has_role_permission("GET", KnowledgeEntry):
            return self.get_permission_denied_response(request, "GET")

        consumer = _get_consumer_or_404(self, id)
        if not consumer:
            return self.not_found("Consumer not found")

        include_inactive = QueryParams.get_bool(request, "include_inactive") is True
        profile = get_knowledge_profile(
            consumer,
            obscure_pii=self.should_obscure_pii(request),
            active_fields_only=not include_inactive,
        )
        return Response(profile, status=status.HTTP_200_OK)

    def patch(self, request, id):
        if not self.has_role_permission("PATCH", KnowledgeEntry):
            return self.get_permission_denied_response(request, "PATCH")

        consumer = _get_consumer_or_404(self, id)
        if not consumer:
            return self.not_found("Consumer not found")

        serializer = KnowledgeProfileEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created_entries = []
        for item in serializer.validated_data["entries"]:
            field = KnowledgeField.objects.filter(id=item["field_id"]).first()
            if not field:
                return self.respond_with(
                    f"Unknown field_id: {item['field_id']}",
                    key="field_id",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            entry = write_knowledge_entry(
                consumer=consumer,
                field=field,
                value=item["value"],
                source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
                confidence=item.get("confidence", 1.0),
                created_by=request.user,
            )
            created_entries.append(entry)

        data = KnowledgeEntryDetailSerializer(created_entries, many=True).data
        data = apply_sensitive_masking_to_entry_data(data, self.should_obscure_pii(request))

        profile = get_knowledge_profile(
            consumer,
            obscure_pii=self.should_obscure_pii(request),
            active_fields_only=True,
        )
        return Response(
            {"created": data, "profile": profile},
            status=status.HTTP_200_OK,
        )


class ConsumerKnowledgeActivity(SmartPaginationAPIView):
    """GET /consumers/<id>/knowledge/activity — chronological entry feed."""

    model = KnowledgeEntry
    list_serializer = KnowledgeActivitySerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def queryset(self, request):
        # Overridden in get via consumer scope; base unused.
        return KnowledgeEntry.objects.none()

    def get(self, request, id):
        if not self.has_permission(request, "GET") or not self.has_role_permission("GET", self.model):
            return self.get_permission_denied_response(request, "GET")

        consumer = _get_consumer_or_404(self, id)
        if not consumer:
            return self.not_found("Consumer not found")

        source = QueryParams.get_str(request, "source")
        if source and source not in Constants.KNOWLEDGE_ENTRY_SOURCES:
            return self.respond_with(
                f"source must be one of {Constants.KNOWLEDGE_ENTRY_SOURCES}",
                key="source",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        queryset = get_activity_queryset(consumer, source=source)
        serializer_class = self.get_list_serializer(request, queryset)
        response = self.paginated_response(queryset, serializer_class)

        if response.status_code != status.HTTP_200_OK:
            return response

        # paginated_response already ran handle_obscure_pii (standard PII);
        # apply knowledge-sensitive masking on top.
        obscure = self.should_obscure_pii(request)
        payload = response.data
        if isinstance(payload, dict) and "results" in payload:
            payload = {
                **payload,
                "results": apply_sensitive_masking_to_entry_data(payload["results"], obscure),
            }
            return Response(payload, status=response.status_code)

        return Response(
            apply_sensitive_masking_to_entry_data(payload, obscure),
            status=response.status_code,
        )


class ConsumerKnowledgeFieldHistory(SmartPaginationAPIView):
    """GET /consumers/<id>/knowledge/fields/<field_id>/history"""

    model = KnowledgeEntry
    list_serializer = KnowledgeActivitySerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def get(self, request, id, field_id):
        if not self.has_permission(request, "GET") or not self.has_role_permission("GET", self.model):
            return self.get_permission_denied_response(request, "GET")

        consumer = _get_consumer_or_404(self, id)
        if not consumer:
            return self.not_found("Consumer not found")

        field = KnowledgeField.objects.filter(id=field_id).first()
        if not field:
            return self.not_found("Knowledge field not found")

        if field.sensitive and self.should_obscure_pii(request):
            # Spec: without Personal Information permission, cannot expand history.
            return Response(
                {
                    "field": {
                        "id": field.id,
                        "key": field.key,
                        "label": field.label,
                        "sensitive": True,
                    },
                    "restricted": True,
                    "detail": Constants.KNOWLEDGE_RESTRICTED_PLACEHOLDER,
                    "results": [],
                },
                status=status.HTTP_200_OK,
            )

        queryset = get_field_history_queryset(consumer, field)
        serializer_class = self.get_list_serializer(request, queryset)
        response = self.paginated_response(queryset, serializer_class)

        if response.status_code != status.HTTP_200_OK:
            return response

        obscure = self.should_obscure_pii(request)
        payload = response.data
        if isinstance(payload, dict) and "results" in payload:
            results = apply_sensitive_masking_to_entry_data(payload["results"], obscure)
            return Response(
                {
                    **payload,
                    "field": {
                        "id": field.id,
                        "key": field.key,
                        "label": field.label,
                        "sensitive": field.sensitive,
                    },
                    "restricted": False,
                    "results": results,
                },
                status=response.status_code,
            )

        return Response(
            {
                "field": {
                    "id": field.id,
                    "key": field.key,
                    "label": field.label,
                    "sensitive": field.sensitive,
                },
                "restricted": False,
                "results": apply_sensitive_masking_to_entry_data(payload, obscure),
            },
            status=response.status_code,
        )
