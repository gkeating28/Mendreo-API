from __future__ import unicode_literals

from rest_framework import status
from rest_framework.response import Response

from ..question.serializers import (
    Question,
    QuestionDetailSerializer,
)

from ..attribute.serializers import (
    AttributeListSerializer,
)

from ..package.serializers import (
    Package,
    PackageDetailSerializer,
)

from ..utils.Views import SmartAPIView
from ..utils.Permissions import IsConsumerPermission

from ..utils import Constants, Api, Subscription as SubscriptionUtils


class Onboarding(SmartAPIView):

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