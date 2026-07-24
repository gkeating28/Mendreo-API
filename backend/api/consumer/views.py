from __future__ import unicode_literals

from django.db.models import Q

from .models import Consumer

from .serializers import (
    ConsumerCreateSerializer,
    ConsumerEditSerializer,
    ConsumerAdminEditSerializer,
    ConsumerListSerializer,
    ConsumerDetailSerializer,
    ConsumerAdminListSerializer,
    ConsumerAdminDetailSerializer
)

from ..utils.Permissions import (
    IsAdminPermission,
    IsConsumerPermission
)

from ..utils import QueryParams, Constants, DateUtils, Token, Subscription as SubscriptionUtils

from ..utils.Views import SmartPaginationAPIView, SmartDetailAPIView


class ListCreate(SmartPaginationAPIView):
    model = Consumer

    list_serializer = ConsumerListSerializer
    detail_serializer = ConsumerDetailSerializer
    create_serializer = ConsumerCreateSerializer

    admin_list_serializer = ConsumerAdminListSerializer

    permission_classes = []

    def add_filters(self, query, request):
        status = QueryParams.get_str(request, "status")
        onboarded = QueryParams.get_bool(request, "onboarded")
        search_term = QueryParams.get_str(request, "search_term")
        subscription_active = QueryParams.get_bool(request, "subscription_active")

        if search_term:
            query = query.filter(
                Q(user__email__icontains=search_term) |
                Q(user__full_name__icontains=search_term)
            )

        if status:
            query = query.filter(user__status=status)

        if onboarded is not None:
            query = query.filter(onboarded=onboarded)

        if subscription_active is not None:
            query = query.filter(subscription__active=subscription_active)

        return query

    def post_response(self, request, instance, data):

        if self.is_anonymous_request():
            data = dict()
            data[Constants.CONSUMER] = ConsumerDetailSerializer(instance).data
            data[Constants.USER_AUTH_TOKENS] = Token.create(instance.user)

        return super(ListCreate, self).post_response(request, instance, data)


class Detail(SmartDetailAPIView):
    permission_classes = [IsAdminPermission | IsConsumerPermission]

    model = Consumer
    detail_serializer = ConsumerDetailSerializer
    edit_serializer = ConsumerEditSerializer

    admin_edit_serializer = ConsumerAdminEditSerializer
    admin_detail_serializer = ConsumerAdminDetailSerializer

    deletable = True

    def queryset(self, request, id):
        if self.is_admin_request():
            return Consumer.objects.filter(user_id=id)

        return Consumer.objects.filter(user_id=self.get_user_from_request().id)

    def add_filters(self, queryset, request):
        if self.is_consumer_request():
            queryset = queryset.filter(user=self.get_user_from_request())

        return queryset

    def handle_delete(self, instance):

        if instance.subscription.payment:
            SubscriptionUtils.cancel(instance.subscription, prevent_cancelling_in_app_subscription=True)

        user = instance.user

        if user == self.get_user_from_request():
            # todo handle GDPR delete
            user.status = Constants.USER_STATUS_DELETED
        else:
            user.status = Constants.USER_STATUS_SUSPENDED

        user.deleted_at = DateUtils.now()
        user.save()

        return super(Detail, self).handle_delete(instance)
