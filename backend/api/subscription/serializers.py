from ..utils.Models import SmartModel
from ..utils.Serializers import serializers, EditModelSerializer, ListModelSerializer

from ..package.models import Package

from ..payment.serializers import (
    PaymentValidateSerializer,
    PaymentCreateSerializer,
    PaymentListSerializer,
    PaymentDetailSerializer
)

from ..utils import DateUtils


from .models import Subscription


class SubscriptionEditSerializer(EditModelSerializer):
    package = serializers.PrimaryKeyRelatedField(queryset=Package.objects.all())
    payment = PaymentValidateSerializer(required=False)

    class Meta:
        model = Subscription
        fields = ["package", "payment"]

    def validate(self, attrs):
        package = attrs.get("package")

        if package and (package.id == self.instance.package.id and self.instance.active is True):
            raise self.raise_validation_error("subscription", "You already have a subscription for this package")

        payment = self.instance.payment

        if payment and (payment.apple_receipt_id or payment.google_receipt_id or payment.stripe_subscription_id):
            raise self.raise_validation_error("subscription", "Please cancel your existing subscription first")

        payment_data = attrs.pop("payment", None)

        if payment_data:
            payment_data["consumer"] = self.instance.consumer
            payment_data["package"] = package.id

            payment_serializer = PaymentCreateSerializer(data=payment_data)
            payment_serializer.is_valid(raise_exception=True)
            payment = payment_serializer.create(payment_serializer.validated_data)
            attrs["payment"] = payment

        active = True if payment else False

        if active:
            attrs["unsubscribed_at"] = None
            attrs["subscribed_at"] = DateUtils.now()

        attrs["active"] = active

        if package:
            attrs["title"] = package.title

        return attrs

    def post_update(self, subscription: SmartModel, nested_relations: dict):

        consumer = subscription.consumer
        if subscription.active and not consumer.onboarded:
            consumer.update_onboarding_status()

        if subscription.active and not consumer.surveyed:
            consumer.update_surveyed_status()

        return


class SubscriptionDetailSerializer(ListModelSerializer):
    payment = PaymentDetailSerializer()

    class Meta:
        model = Subscription
        fields = "__all__"


class SubscriptionAdminDetailSerializer(ListModelSerializer):

    class Meta:
        model = Subscription
        fields = "__all__"
