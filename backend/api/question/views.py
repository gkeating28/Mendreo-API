from __future__ import unicode_literals

from .models import Question

from .serializers import (
    QuestionCreateSerializer,
    QuestionEditSerializer,
    QuestionListSerializer,
    QuestionDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView

from ..utils import QueryParams


class ListCreate(SmartPaginationAPIView):

    model = Question
    list_serializer = QuestionListSerializer
    detail_serializer = QuestionDetailSerializer
    create_serializer = QuestionCreateSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    allow_disable_pagination = True

    def add_filters(self, queryset, request):
        search_term = QueryParams.get_str(request, "search_term")
        session_id = QueryParams.get_str(request, "session_id")
        survey = QueryParams.get_bool(request, "survey")

        if search_term:
            queryset = queryset.filter(title__icontains=search_term)

        if survey is not None:
            queryset = queryset.filter(survey=survey)

        if session_id is not None:
            queryset = queryset.filter(session_id=session_id)

        return queryset

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Question
    edit_serializer = QuestionEditSerializer
    detail_serializer = QuestionDetailSerializer

    deletable = True

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()
