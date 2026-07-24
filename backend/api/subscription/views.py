from __future__ import unicode_literals

from .models import Subscription

from .serializers import (
    SubscriptionEditSerializer,
    SubscriptionDetailSerializer,
)

from ..utils.Permissions import (
    IsConsumerPermission,
)

from ..utils.Views import SmartDetailAPIView
from ..utils import Subscription as SubscriptionUtils


class Detail(SmartDetailAPIView):
    permission_classes = [IsConsumerPermission]

    model = Subscription
    detail_serializer = SubscriptionDetailSerializer
    edit_serializer = SubscriptionEditSerializer
    partial = False

    deletable = True

    def queryset(self, request, id):
        return Subscription.objects.filter(consumer=self.get_consumer_from_request())

    def handle_delete(self, instance):

        instance = SubscriptionUtils.cancel(subscription=instance, prevent_cancelling_in_app_subscription=True)

        return instance
