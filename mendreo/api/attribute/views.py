from __future__ import unicode_literals

from rest_framework import status
from rest_framework.response import Response

from .models import Attribute

from .serializers import (
    AttributeCreateSerializer,
    AttributeEditSerializer,
    AttributeDetailSerializer,
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView

from ..utils import QueryParams, Constants

import datetime


class ListCreate(SmartPaginationAPIView):

    model = Attribute
    list_serializer = AttributeDetailSerializer
    detail_serializer = AttributeDetailSerializer
    create_serializer = AttributeCreateSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    def post(self, request):
        question = request.data.get("question", None)
        if self.is_consumer_request() and question == Constants.QUESTION_ID_DOB:
            return handle_date_of_birth(self, request)

        return super(ListCreate, self).post(request)

    def add_filters(self, queryset, request):
        consumer_id = QueryParams.get_str(request, "consumer_id")

        self.allow_disable_pagination = consumer_id is not None

        if self.is_consumer_request():
            consumer_id = self.get_consumer_from_request().user_id

        if consumer_id:
            queryset = queryset.filter(consumer_id=consumer_id)

        return queryset

    def override_post_data(self, request, data):
        self.inject_user(request, key="consumer")
        return data

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_consumer_request()


class Detail(SmartDetailAPIView):

    model = Attribute
    edit_serializer = AttributeEditSerializer
    detail_serializer = AttributeDetailSerializer

    permission_classes = [IsAdminPermission | IsConsumerPermission]

    def has_permission(self, request, method):
        if method == "GET":
            return True

        return self.is_consumer_request()


def handle_date_of_birth(view: SmartPaginationAPIView, request):
    consumer = view.get_consumer_from_request()

    value = request.data.get("value", None)
    try:
        date_of_birth = datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except Exception as e:
        data = {"value": f"'{value}' is not a valid data in format 'YYYY-MM-DD"}
        return Response(data, status=status.HTTP_400_BAD_REQUEST)

    today = datetime.datetime.today()
    threshold = datetime.date(today.year - Constants.CONSUMER_MINIMUM_AGE, date_of_birth.month, date_of_birth.day)

    if date_of_birth > threshold:
        data = {"value": f"must be at least {Constants.CONSUMER_MINIMUM_AGE}"}
        return Response(data, status=status.HTTP_400_BAD_REQUEST)

    consumer.date_of_birth = date_of_birth
    consumer.save()
    consumer.update_onboarding_status()
    consumer.update_surveyed_status()

    data = {
        "id": Constants.QUESTION_ID_DOB,
        "key": Constants.QUESTION_ID_DOB,
        "value": value,
        "question": Constants.QUESTION_ID_DOB
    }

    return Response(data, status=status.HTTP_201_CREATED)


