from __future__ import unicode_literals

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response

from .models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from .serializers import (
    KnowledgeEntryCreateSerializer,
    KnowledgeEntryDetailSerializer,
    KnowledgeEntryListSerializer,
    KnowledgeExtractionTestSerializer,
    KnowledgeFieldCreateSerializer,
    KnowledgeFieldDetailSerializer,
    KnowledgeFieldEditSerializer,
    KnowledgeFieldListSerializer,
    KnowledgeQuestionCreateSerializer,
    KnowledgeQuestionDetailSerializer,
    KnowledgeQuestionEditSerializer,
    KnowledgeQuestionListSerializer,
)
from .services import apply_sensitive_masking_to_entry_data, test_extraction
from ..utils import QueryParams
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView, SmartDetailAPIView, SmartPaginationAPIView


class FieldListCreate(SmartPaginationAPIView):
    model = KnowledgeField
    list_serializer = KnowledgeFieldListSerializer
    detail_serializer = KnowledgeFieldDetailSerializer
    create_serializer = KnowledgeFieldCreateSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def add_filters(self, queryset, request):
        search_term = QueryParams.get_str(request, "search_term")
        category = QueryParams.get_str(request, "category")
        active = QueryParams.get_bool(request, "active")

        if search_term:
            queryset = queryset.filter(
                Q(label__icontains=search_term) | Q(key__icontains=search_term)
            )
        if category:
            queryset = queryset.filter(category__iexact=category)
        if active is not None:
            queryset = queryset.filter(active=active)

        return queryset.order_by("category", "label")


class FieldDetail(SmartDetailAPIView):
    model = KnowledgeField
    edit_serializer = KnowledgeFieldEditSerializer
    detail_serializer = KnowledgeFieldDetailSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    deletable = True


class QuestionListCreate(SmartPaginationAPIView):
    model = KnowledgeQuestion
    list_serializer = KnowledgeQuestionListSerializer
    detail_serializer = KnowledgeQuestionDetailSerializer
    create_serializer = KnowledgeQuestionCreateSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def add_filters(self, queryset, request):
        search_term = QueryParams.get_str(request, "search_term")
        active = QueryParams.get_bool(request, "active")
        target_field_id = QueryParams.get_str(request, "target_field_id")
        trigger = QueryParams.get_str(request, "trigger")
        flow = QueryParams.get_str(request, "flow")

        queryset = KnowledgeQuestionListSerializer.optimise(queryset)

        if search_term:
            queryset = queryset.filter(prompt__icontains=search_term)
        if active is not None:
            queryset = queryset.filter(active=active)
        if target_field_id:
            queryset = queryset.filter(target_field_id=target_field_id)
        if trigger:
            queryset = queryset.filter(trigger=trigger)
        if flow:
            queryset = queryset.filter(flows__contains=[flow])

        return queryset.order_by("order", "created_at")


class QuestionDetail(SmartDetailAPIView):
    model = KnowledgeQuestion
    edit_serializer = KnowledgeQuestionEditSerializer
    detail_serializer = KnowledgeQuestionDetailSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    deletable = True

    def queryset(self, request, id):
        return KnowledgeQuestionListSerializer.optimise(super().queryset(request, id))

    def handle_delete(self, instance):
        KnowledgeEntry.objects.filter(knowledge_question=instance).delete()
        return instance.delete()


class QuestionTestExtraction(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True
    model = KnowledgeQuestion

    def post(self, request, id):
        if not self.has_role_permission("POST", KnowledgeQuestion):
            return self.get_permission_denied_response(request, "POST")

        try:
            question = KnowledgeQuestion.objects.select_related("target_field").get(id=id)
        except KnowledgeQuestion.DoesNotExist:
            return self.not_found()

        serializer = KnowledgeExtractionTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        extraction_prompt = serializer.validated_data.get("extraction_prompt") or question.extraction_prompt
        if not extraction_prompt:
            return self.respond_with(
                "extraction_prompt is required on the question or in the request body",
                key="extraction_prompt",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = test_extraction(
                extraction_prompt=extraction_prompt,
                sample_reply=serializer.validated_data["sample_reply"],
                value_type=question.target_field.value_type,
            )
        except Exception as exc:
            return self.respond_with(
                f"Extraction failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "value": result.get("value"),
                "confidence": result.get("confidence"),
                "target_field": {
                    "id": question.target_field_id,
                    "key": question.target_field.key,
                    "label": question.target_field.label,
                    "value_type": question.target_field.value_type,
                },
            },
            status=status.HTTP_200_OK,
        )


class _SensitiveEntryMixin:
    def handle_obscure_pii(self, request, data):
        data = super().handle_obscure_pii(request, data)
        return apply_sensitive_masking_to_entry_data(data, self.should_obscure_pii(request))


class EntryListCreate(_SensitiveEntryMixin, SmartPaginationAPIView):
    model = KnowledgeEntry
    list_serializer = KnowledgeEntryListSerializer
    detail_serializer = KnowledgeEntryDetailSerializer
    create_serializer = KnowledgeEntryCreateSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def post(self, request):
        # Pass request into serializer context so created_by / source can be set.
        if not self.has_permission(request, "POST") or not self.has_role_permission("POST", self.model):
            return self.get_permission_denied_response(request, "POST")

        data = request.data
        if hasattr(request.data, "_mutable"):
            request.data._mutable = True
        data = self.override_post_data(request, data)
        if hasattr(request.data, "_mutable"):
            request.data._mutable = False

        create_serializer = self.create_serializer(
            data=data,
            context={"request": request},
        )
        create_serializer.is_valid(raise_exception=True)
        instance = create_serializer.save()
        detail_data = self.detail_serializer(instance).data
        return self.post_response(request, instance, detail_data)

    def add_filters(self, queryset, request):
        consumer_id = QueryParams.get_str(request, "consumer_id")
        field_id = QueryParams.get_str(request, "field_id")
        source = QueryParams.get_str(request, "source")

        queryset = KnowledgeEntryListSerializer.optimise(queryset)

        if consumer_id:
            queryset = queryset.filter(consumer_id=consumer_id)
        if field_id:
            queryset = queryset.filter(field_id=field_id)
        if source:
            queryset = queryset.filter(source=source)

        return queryset.order_by("-created_at")


class EntryDetail(_SensitiveEntryMixin, SmartDetailAPIView):
    model = KnowledgeEntry
    detail_serializer = KnowledgeEntryDetailSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    deletable = True

    def queryset(self, request, id):
        return KnowledgeEntryListSerializer.optimise(super().queryset(request, id))
