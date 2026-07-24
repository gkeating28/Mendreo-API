from ..utils.Serializers import serializers, ValidateModelSerializer, CreateModelSerializer, ListModelSerializer

from .models import Payment

from ..package.models import Package

from ..price.serializers import PriceDetailSerializer

from ..utils import InAppPayment, Exception as CustomException, StripeSubscription


class PaymentValidateSerializer(ValidateModelSerializer):

    stripe_payment_method_id = serializers.CharField(required=False, allow_null=True)
    stripe_payment_intent_id = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = Payment
        fields = ["apple_receipt_id", "google_receipt_id", "stripe_payment_method_id", "stripe_payment_intent_id"]

    def validate(self, attrs):
        apple_receipt_id = attrs.get("apple_receipt_id", None)
        google_receipt_id = attrs.get("google_receipt_id", None)
        stripe_payment_method_id = attrs.get("stripe_payment_method_id", None)

        if not apple_receipt_id and not google_receipt_id and not stripe_payment_method_id:
            self.raise_validation_error("details", "invalid details provided")

        return attrs


class PaymentCreateSerializer(CreateModelSerializer):
    package = serializers.PrimaryKeyRelatedField(queryset=Package.objects.all())
    signature = serializers.CharField(required=False)
    stripe_payment_method_id = serializers.CharField(required=False, allow_null=True)
    stripe_payment_intent_id = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = Payment
        fields = [
            "consumer",
            "apple_receipt_id",
            "google_receipt_id",
            "package",
            "signature",
            "stripe_payment_method_id",
            "stripe_payment_intent_id",
        ]

    def validate(self, attrs):
        attrs = payment_validation(self, attrs)

        package = attrs.pop("package")
        price = package.price
        attrs["price"] = price

        return attrs


class PaymentListSerializer(ListModelSerializer):

    method = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "price",
            "method",
        ]

    def get_method(self, payment):
        if payment.apple_receipt_id:
            return "in_app_apple"

        if payment.google_receipt_id:
            return "in_app_google"

        if payment.stripe_subscription_id:
            return "stripe"

        return "unknown"


class PaymentDetailSerializer(PaymentListSerializer):

    price = PriceDetailSerializer()


def payment_validation(serializer, attrs):
    package = attrs.get("package")
    price = package.price
    consumer = attrs["consumer"]

    apple_receipt_id = attrs.get("apple_receipt_id", None)
    google_receipt_id = attrs.get("google_receipt_id", None)

    signature = attrs.pop("signature", None)

    stripe_payment_method_id = attrs.pop("stripe_payment_method_id", None)
    stripe_payment_intent_id = attrs.pop("stripe_payment_intent_id", None)

    if apple_receipt_id:
        hash = Payment.hash(apple_receipt_id)
        if Payment.objects.filter(apple_receipt_id_hash=hash).exists():
            serializer.raise_validation_error(
                "apple_receipt_id",
                "A subscription with this receipt already exists. Please contact support for assistance"
            )

        InAppPayment.apple_validator(apple_receipt_id, price)

    elif google_receipt_id:
        hash = Payment.hash(google_receipt_id)
        if Payment.objects.filter(google_receipt_id_hash=hash).exists():
            serializer.raise_validation_error(
                "google_receipt_id",
                "A subscription with this receipt already exists. Please contact support for assistance"
            )

        InAppPayment.google_validator(google_receipt_id, signature, price)

    elif stripe_payment_method_id:
        if stripe_payment_intent_id and Payment.objects.filter(stripe_receipt_id=stripe_payment_intent_id).exists():
            serializer.raise_validation_error(
                "stripe_payment_intent_id",
                "A subscription with this receipt already exists. Please contact support for assistance"
            )
        return stripe_payment_validation(serializer, attrs, consumer, package, stripe_payment_method_id, stripe_payment_intent_id)

    else:
        raise serializer.raise_validation_error(
            "payment",
            "invalid, must specify one of ['apple_receipt_id','google_receipt_id','stripe_payment_method_id']"
        )

    return attrs


def stripe_payment_validation(serializer, attrs, consumer, package, payment_method_id: str, payment_intent_id: str = None):

    if payment_intent_id:
        payment_intent = StripeSubscription.get_payment_intent(payment_intent_id)
        stripe_subscription = payment_intent.invoice.subscription
    else:
        stripe_subscription = StripeSubscription.create(consumer, payment_method_id, package)
        payment_intent = stripe_subscription.latest_invoice.payment_intent

    try:
        if not payment_intent.status == "succeeded":
            payment_intent.confirm()
    except Exception as error:
        serializer.raise_validation_error("payment", error)

    if StripeSubscription.requires_user_action(payment_intent):
        data = {
            "payment_intent_id": payment_intent.id,
            "payment_method_id": payment_method_id,
            "client_secret": payment_intent.client_secret,
            "requires_action": True,
        }
        raise CustomException.raise_sca_error(data)

    elif not StripeSubscription.payment_intent_paid(payment_intent):
        raise serializer.raise_validation_error(
            "An unexpected error occurred, you have not been charged, please try again"
        )

    attrs["stripe_receipt_id"] = payment_intent.id
    attrs["stripe_subscription_id"] = stripe_subscription.id

    return attrs
