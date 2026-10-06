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
from .dry_run import dry_run_step, step_fields_from_data
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
        query = query.prefetch_related("steps", "questions").filter(authoring_snapshot=False)

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

    def add_filters(self, queryset, request):
        return queryset.filter(authoring_snapshot=False)

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

    def post(self, request, id, step_id=None):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "POST")

        exercise = Exercise.objects.filter(id=id).first()
        if exercise is None:
            return self.not_found()
        step = None
        if step_id:
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

        step_fields, order_error = step_fields_from_data(request.data)
        if order_error:
            return self.respond_with(
                order_error,
                key="order",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        transcript = None
        if isinstance(request.data, dict):
            transcript = request.data.get("transcript") or None

        try:
            payload = dry_run_step(exercise, step, consumer, transcript, step_fields)
        except Exception as exc:
            return self.respond_with(
                f"Dry run failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload, status=status.HTTP_200_OK)


class TestRun(SmartAPIView):
    """Start a flagged test run from the exercise form, including unsaved edits."""

    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def post(self, request, id):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "POST")

        exercise = Exercise.objects.filter(id=id, authoring_snapshot=False).first()
        if exercise is None:
            return self.not_found()

        consumer_id = request.data.get("consumer_id") if isinstance(request.data, dict) else None
        if not consumer_id:
            return self.respond_with(
                "Choose a user to dry-run against.",
                key="consumer_id",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        from ..consumer.models import Consumer
        from ..utils.authoring_run import (
            delete_admin_authoring_runs,
            start_authoring_test,
            write_authoring_snapshot,
        )

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

        admin = self.get_admin_from_request()
        try:
            with transaction.atomic():
                delete_admin_authoring_runs(admin, exercise)
                snapshot = write_authoring_snapshot(exercise, request.data)
                session, opening, session_state = start_authoring_test(
                    snapshot, consumer, admin
                )
        except ValueError as exc:
            return self.respond_with(str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return self.respond_with(
                f"Dry run failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "opening_message": opening.text,
                "session_state": session_state,
                "session_id": session.id,
                "snapshot_exercise_id": snapshot.id,
            },
            status=status.HTTP_200_OK,
        )


class TestRunMessage(SmartAPIView):
    """Send one turn on a flagged test run. Runs in this request."""

    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def post(self, request, id, run_id):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "POST")

        exercise = Exercise.objects.filter(id=id, authoring_snapshot=False).first()
        if exercise is None:
            return self.not_found()
        if self.should_obscure_pii(request):
            return self.respond_with(
                "Personal Information view permission is required to test against a user",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        from ..session.models import Session
        from ..utils.authoring_run import from_suggested_response, post_authoring_message

        session = (
            Session.objects.select_related("exercise", "consumer")
            .filter(
                id=run_id,
                authoring_test=True,
                exercise__authoring_snapshot=True,
                exercise__authoring_source_id=exercise.id,
            )
            .first()
        )
        if session is None:
            return self.not_found()
        if session.completed or session.state == Constants.SESSION_STATE_COMPLETED:
            return self.respond_with(
                "Not allowed to send messages for past sessions.",
                key="session",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                payload = post_authoring_message(
                    session,
                    request.data.get("text") if isinstance(request.data, dict) else "",
                    from_suggested_response(request.data),
                )
        except ValueError as exc:
            return self.respond_with(str(exc), status_code=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return self.respond_with(
                f"Dry run failed: {exc}",
                status_code=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload, status=status.HTTP_200_OK)


class TestRunDetail(SmartAPIView):
    """Hard-delete one flagged test run and its snapshot."""

    permission_classes = [IsAdminPermission]
    role_permission = True
    model = Exercise

    def delete(self, request, id, run_id):
        if not self.has_role_permission("POST", Exercise):
            return self.get_permission_denied_response(request, "DELETE")

        exercise = Exercise.objects.filter(id=id, authoring_snapshot=False).first()
        if exercise is None:
            return self.not_found()
        if self.should_obscure_pii(request):
            return self.respond_with(
                "Personal Information view permission is required to test against a user",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        from ..session.models import Session
        from ..utils.authoring_run import AuthoringDeleteRefused, delete_authoring_run

        session = (
            Session.objects.select_related("exercise")
            .filter(
                id=run_id,
                authoring_test=True,
                exercise__authoring_snapshot=True,
                exercise__authoring_source_id=exercise.id,
            )
            .first()
        )
        if session is None:
            return self.not_found()
        try:
            delete_authoring_run(session)
        except AuthoringDeleteRefused:
            return self.not_found()
        return Response(status=status.HTTP_204_NO_CONTENT)


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

        validated = serializer.validated_data
        overrides = {}
        for field in (
            "check_in_tone",
            "check_in_instruction",
            "check_in_goal",
            "check_in_summary_prompt",
        ):
            if field in validated:
                overrides[field] = "" if validated[field] is None else validated[field]

        try:
            payload = test_pre_exercise_prompt(
                exercise,
                consumer,
                run_dry_run=validated.get("run_dry_run", False),
                transcript=validated.get("transcript") or None,
                overrides=overrides,
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
