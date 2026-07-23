from __future__ import unicode_literals

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response

from .models import Exercise

from .serializers import (
    ExerciseCreateSerializer,
    ExerciseEditSerializer,
    ExerciseListSerializer,
    ExerciseDetailSerializer,
    ExerciseAdminListSerializer,
    ExerciseAdminDetailSerializer,
    ExerciseDuplicateSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import QueryParams, Constants

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView, SmartAPIView


class ListCreate(SmartPaginationAPIView):

    model = Exercise
    list_serializer = ExerciseListSerializer
    detail_serializer = ExerciseDetailSerializer
    create_serializer = ExerciseCreateSerializer

    admin_list_serializer = ExerciseAdminListSerializer
    admin_detail_serializer = ExerciseAdminDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]
    role_permission = True

    def add_filters(self, query, request):
        # Serializers render nested steps/questions; prefetch to avoid N+1
        # (each extra query costs a full round-trip to the remote database).
        query = query.prefetch_related("steps", "questions")

        status_ = QueryParams.get_str(request, "status")
        search_term = QueryParams.get_str(request, "search_term")

        if self.is_consumer_request():
            status_ = Constants.EXERCISE_STATUS_PUBLISHED

        if search_term:
            query = query.filter(title__icontains=search_term)

        if status_:
            query = query.filter(status=status_)

        return query

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]
    role_permission = True 

    model = Exercise
    edit_serializer = ExerciseEditSerializer
    detail_serializer = ExerciseDetailSerializer

    admin_detail_serializer = ExerciseAdminDetailSerializer

    deletable = True

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()
    
    
class DuplicateExerciseView(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def post(self, request):
        data = request.data

        serializer = ExerciseDuplicateSerializer(data=data)

        serializer.is_valid(raise_exception=True)

        instance = serializer.create(serializer.validated_data)

        serializer = ExerciseAdminDetailSerializer(instance)

        return Response(serializer.data, status=status.HTTP_201_CREATED)
