from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from ..utils import QueryParams
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView, SmartDetailAPIView, SmartPaginationAPIView
from .indexing import index_now
from .models import KnowledgeChunk, KnowledgeSource
from .search import search_chunks
from .serializers import (
    KnowledgeChunkListSerializer,
    KnowledgeSourceCreateSerializer,
    KnowledgeSourceDetailSerializer,
    KnowledgeSourceEditSerializer,
    KnowledgeSourceListSerializer,
    approve_block,
    mark_approved,
    mark_submitted,
)


class SourceListCreate(SmartPaginationAPIView):
    model = KnowledgeSource
    list_serializer = KnowledgeSourceListSerializer
    detail_serializer = KnowledgeSourceDetailSerializer
    create_serializer = KnowledgeSourceCreateSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    allow_disable_pagination = True

    def add_filters(self, queryset, request):
        search_term = QueryParams.get_str(request, "search_term")
        kind = QueryParams.get_str(request, "kind")
        source_status = QueryParams.get_str(request, "status")
        if search_term:
            queryset = queryset.filter(title__icontains=search_term)
        if kind:
            queryset = queryset.filter(kind=kind)
        if source_status:
            queryset = queryset.filter(status=source_status)
        return queryset.order_by("-updated_at")


class SourceDetail(SmartDetailAPIView):
    model = KnowledgeSource
    edit_serializer = KnowledgeSourceEditSerializer
    detail_serializer = KnowledgeSourceDetailSerializer
    permission_classes = [IsAdminPermission]
    role_permission = True
    deletable = True


class SourceSubmit(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def post(self, request, id):
        if not _has_verb(self, "edit"):
            return self.get_permission_denied_response(request, "POST")
        source = KnowledgeSource.objects.filter(id=id).first()
        if source is None:
            return self.not_found()
        mark_submitted(source, request.user.admin)
        return Response(KnowledgeSourceDetailSerializer(source).data)


class SourceApprove(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def post(self, request, id):
        if not _has_verb(self, "approve"):
            return self.get_permission_denied_response(request, "POST")
        source = KnowledgeSource.objects.filter(id=id).first()
        if source is None:
            return self.not_found()
        reason = approve_block(source, request.user.admin)
        if reason:
            return self.respond_with(reason, status_code=status.HTTP_400_BAD_REQUEST)
        mark_approved(source, request.user.admin)
        return _index_response(self, source, published_now=True)


class SourceReindex(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def post(self, request, id):
        if not _has_verb(self, "edit"):
            return self.get_permission_denied_response(request, "POST")
        source = KnowledgeSource.objects.filter(id=id).first()
        if source is None:
            return self.not_found()
        from ..utils import Constants

        if source.status != Constants.KNOWLEDGE_SOURCE_STATUS_PUBLISHED:
            return self.respond_with(
                "Only a published source can be re-indexed.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return _index_response(self, source, published_now=False)


class SourceChunks(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def get(self, request, id):
        if not _has_verb(self, "view"):
            return self.get_permission_denied_response(request, "GET")
        source = KnowledgeSource.objects.filter(id=id).first()
        if source is None:
            return self.not_found()
        queryset = KnowledgeChunk.objects.filter(source=source).order_by("ordinal", "id")
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            KnowledgeChunkListSerializer(page, many=True).data
        )


class SourceSearch(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True

    def post(self, request):
        if not _has_verb(self, "view"):
            return self.get_permission_denied_response(request, "POST")
        query = (request.data.get("query") or "").strip()
        if not query:
            return self.respond_with(
                "query is required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        exercise_id = request.data.get("exercise_id") or None
        selected, below = search_chunks(query, exercise_id)
        return Response({"chunks": selected, "below_threshold": below})


def _index_response(view, source: KnowledgeSource, *, published_now: bool):
    """Run the index in this request and tell the caller how many chunks landed."""
    import logging

    try:
        count = index_now(source.id)
    except Exception as error:
        logging.getLogger(__name__).exception(
            "knowledge source %s was not indexed", source.id
        )
        reason = str(error).splitlines()[0][:300] or "unknown error"
        message = f"Indexing failed: {reason}"
        if published_now:
            message = f"The source was published, but indexing failed: {reason}"
        return view.respond_with(message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if count is None:
        source.refresh_from_db()
        data = KnowledgeSourceDetailSerializer(source).data
        data["indexing"] = True
        data["detail"] = (
            "Indexing is running. It takes about 3 minutes. "
            "Refresh this source to see the chunks."
        )
        return Response(data)
    if count <= 0:
        message = "There was no text to index."
        if published_now:
            message = "The source was published, but there was no text to index."
        return view.respond_with(message, status_code=status.HTTP_400_BAD_REQUEST)
    source.refresh_from_db()
    data = KnowledgeSourceDetailSerializer(source).data
    data["indexed_chunks"] = count
    return Response(data)


def _has_verb(view, verb: str) -> bool:
    if not view.is_admin_request():
        return False
    if not view.is_role_permission():
        return True
    permissions = view.get_role_permission(KnowledgeSource)
    if permissions is None:
        return True
    return verb in permissions
