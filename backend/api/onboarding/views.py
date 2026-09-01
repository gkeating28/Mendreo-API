from __future__ import unicode_literals

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .serializers import OnboardingAnswersSerializer
from .services import (
    build_flow_payload,
    build_status_payload,
    complete_onboarding_with_placeholders,
    resolve_variant,
    restart_onboarding,
    submit_flow_answers,
)
from ..knowledge.services import get_knowledge_profile

from ..question.serializers import (
    Question,
    QuestionDetailSerializer,
)

from ..package.serializers import (
    Package,
    PackageDetailSerializer,
)

from ..utils.Views import SmartAPIView
from ..utils.Permissions import IsConsumerPermission

from ..utils import Constants, Api, QueryParams, Subscription as SubscriptionUtils


class Onboarding(SmartAPIView):
    """Legacy GET /onboarding — Attribute-based questions + packages."""

    permission_classes = [IsConsumerPermission]

    def get(self, request):

        consumer = self.get_consumer_from_request()

        if Api.BYPASS_SUBSCRIPTION:
            SubscriptionUtils.validate_subscription(consumer.subscription)
            consumer.refresh_from_db()

        questions = Question.objects.filter(survey=False, exercise__isnull=True)
        questions_data = Question.get_with_attributes(questions, consumer)

        if not consumer.date_of_birth:
            questions_data = [
                {
                    "id": Constants.QUESTION_ID_DOB,
                    "type": "date",
                    "title": "What is your date of birth?",
                    "order": -1,
                    "attribute_key": Constants.QUESTION_ID_DOB,
                    "suggested_responses": [],
                },
                *questions_data,
            ]

        # Hide paywall packages while billing is bypassed.
        if Api.BYPASS_SUBSCRIPTION:
            packages_data = []
        else:
            packages = Package.objects.exclude(default=True)
            packages = PackageDetailSerializer.optimise(packages)
            packages_data = PackageDetailSerializer(packages, many=True).data

        data = {
            "onboarded": consumer.onboarded,
            "questions": questions_data,
            "packages": packages_data
        }

        return Response(data, status=status.HTTP_200_OK)


class OnboardingStatus(SmartAPIView):
    """Home icon state: onboarded, refresh_due, recommended variant."""

    permission_classes = [IsConsumerPermission]

    def get(self, request):
        consumer = self.get_consumer_from_request()
        return Response(build_status_payload(consumer), status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "GET"


class OnboardingFlow(SmartAPIView):
    """V2 flow payload driven by KnowledgeQuestion membership + per-variant order."""

    permission_classes = [IsConsumerPermission]

    def get(self, request):
        consumer = self.get_consumer_from_request()
        requested = QueryParams.get_str(request, "variant")
        try:
            variant = resolve_variant(consumer, requested)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        return Response(build_flow_payload(consumer, variant), status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "GET"


class OnboardingAnswers(SmartAPIView):
    """Commit flow answers → Knowledge Entries (source=question)."""

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        serializer = OnboardingAnswersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = submit_flow_answers(
                consumer,
                variant=data["variant"],
                answers=data["answers"],
                complete=data.get("complete", True),
            )
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "POST"


class OnboardingKnowledge(SmartAPIView):
    """GET /onboarding/knowledge — this consumer's stored onboarding + check-in answers."""

    permission_classes = [IsConsumerPermission]

    def get(self, request):
        consumer = self.get_consumer_from_request()
        return Response(
            get_knowledge_profile(consumer, obscure_pii=False, active_fields_only=True),
            status=status.HTTP_200_OK,
        )

    def has_permission(self, request, method):
        return method == "GET"


class OnboardingComplete(SmartAPIView):
    """Testing shortcut: submit placeholder answers and mark the flow complete."""

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        try:
            result = complete_onboarding_with_placeholders(consumer)
        except ValidationError as exc:
            return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "POST"


class OnboardingRestart(SmartAPIView):
    """Testing shortcut: clear onboarding so the initial flow can be re-run."""

    permission_classes = [IsConsumerPermission]

    def post(self, request):
        consumer = self.get_consumer_from_request()
        return Response(restart_onboarding(consumer), status=status.HTTP_200_OK)

    def has_permission(self, request, method):
        return method == "POST"
