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
from .pre_exercise import test_pre_exercise_prompt
from .pre_exercise_serializers import PreExerciseTestSerializer
from .dry_run import dry_run_step
from ..utils.authoring import authoring_warnings, lint_catalogue

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
    allow_disable_pagination = True

    def add_filters(self, query, request):
        # Serializers render nested steps/questions; prefetch to avoid N+1
        # (each extra query costs a full round-trip to the remote database).
        query = query.prefetch_related("steps", "questions")

        status_ = QueryParams.get_str(request, "status")
        search_term = QueryParams.get_str(request, "search_term")
        pre_exercise = QueryParams.get_str(request, "pre_exercise")
        category = QueryParams.get_str(request, "category")

        if self.is_consumer_request():
            status_ = Constants.EXERCISE_STATUS_PUBLISHED

        if search_term:
            query = query.filter(title__icontains=search_term)

        if status_:
            query = query.filter(status=status_)

        if category:
            query = query.filter(category__iexact=category)

        if pre_exercise and pre_exercise != "all":
            if pre_exercise == "enabled":
                query = query.filter(check_in_enabled=True)
            elif pre_exercise == "disabled":
                query = query.filter(check_in_enabled=False)

        return query

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_admin_request()

    def post_response(self, request, instance, data):
        data = dict(data)
        data["warnings"] = authoring_warnings(instance)
        return super().post_response(request, instance, data)


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

    def patch_response(self, data, instance):
        data = dict(data)
        data["warnings"] = authoring_warnings(instance)
        return super().patch_response(data, instance)


class ExerciseLint(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def get(self, request):
        if not self.has_role_permission("GET", Exercise):
            return self.get_permission_denied_response(request, "GET")
        return Response(lint_catalogue(), status=status.HTTP_200_OK)


class StepDryRun(SmartAPIView):
    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def post(self, request, id, step_id):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "POST")

        exercise = Exercise.objects.filter(id=id).first()
        if exercise is None:
            return self.not_found()
        step = exercise.steps.filter(id=step_id).first()
        if step is None:
            return self.not_found()

        consumer_id = request.data.get("consumer_id") if isinstance(request.data, dict) else None
        if not consumer_id:
            return self.respond_with(
                "Choose a user to dry-run against.",
                key="consumer_id",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from ..consumer.models import Consumer

        consumer = Consumer.objects.select_related("user").filter(pk=consumer_id).first()
        if consumer is None:
            return self.respond_with(
                "Consumer not found",
                key="consumer_id",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        if self.should_obscure_pii(request):
            return self.respond_with(
                "Personal Information view permission is required to test against a user",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        transcript = None
        if isinstance(request.data, dict):
            transcript = request.data.get("transcript") or None

        try:
            payload = dry_run_step(exercise, step, consumer, transcript)
        except Exception as exc:
            return self.respond_with(
                f"Dry run failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload, status=status.HTTP_200_OK)


class DuplicateExerciseView(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def post(self, request):
        data = request.data

        serializer = ExerciseDuplicateSerializer(data=data)

        serializer.is_valid(raise_exception=True)

        instance = serializer.create(serializer.validated_data)

        serializer = ExerciseAdminDetailSerializer(instance)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class TestPreExercisePrompt(SmartAPIView):
    """Resolve pre-exercise tokens for a user; optional dry-run opening turn (no persist)."""

    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def post(self, request, id):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "POST")

        try:
            exercise = Exercise.objects.get(id=id)
        except Exercise.DoesNotExist:
            return self.not_found()

        serializer = PreExerciseTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from ..consumer.models import Consumer

        consumer_id = serializer.validated_data["consumer_id"]
        try:
            consumer = Consumer.objects.select_related("user").get(pk=consumer_id)
        except Consumer.DoesNotExist:
            return self.respond_with(
                "Consumer not found",
                key="consumer_id",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # Directory lookup is PII-gated (spec §2.5.3).
        if self.should_obscure_pii(request):
            return self.respond_with(
                "Personal Information view permission is required to test against a user",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        try:
            payload = test_pre_exercise_prompt(
                exercise,
                consumer,
                run_dry_run=serializer.validated_data.get("run_dry_run", False),
            )
        except Exception as exc:
            return self.respond_with(
                f"Pre-exercise test failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(payload, status=status.HTTP_200_OK)


class ExerciseTokens(SmartAPIView):
    """Token names the check-in and step resolver can fill for this exercise."""

    permission_classes = [IsAdminPermission]
    model = Exercise

    def get(self, request, id):
        if not self.has_permission(request, "GET"):
            return self.get_permission_denied_response(request, "GET")

        try:
            exercise = Exercise.objects.prefetch_related("steps", "questions").get(id=id)
        except Exercise.DoesNotExist:
            return self.not_found()

        from ..utils.prompt_blocks import token_catalogue

        return Response({"tokens": token_catalogue(exercise)}, status=status.HTTP_200_OK)
