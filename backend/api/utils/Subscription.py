import stripe
from rest_framework import status

from ..package.models import Package

from ..utils import InAppPayment, Exception as CustomException, DateUtils, StripeSubscription


def cancel(subscription, prevent_cancelling_in_app_subscription=True):
    if subscription.active is False:
        return CustomException.raise_error(
            "Your subscription is not active.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if prevent_cancelling_in_app_subscription:
        if subscription.payment.apple_receipt_id or subscription.payment.google_receipt_id:
            name = "Apple App Store" if subscription.payment.apple_receipt_id else "Google Play Store"
            return CustomException.raise_error(
                f"Please visit the {name} to cancel this subscription",
                status_code=status.HTTP_400_BAD_REQUEST
            )

    if subscription.payment.stripe_subscription_id:
        try:
            StripeSubscription.cancel(subscription.payment.stripe_subscription_id)
        except stripe.InvalidRequestError as e:
            # subscription cancelled off platform
            if "No such subscription" not in str(e):
                raise e

    subscription.payment = None
    subscription.unsubscribed_at = DateUtils.now()
    subscription.active = False
    subscription.package = Package.get_default()
    subscription.save()

    subscription.consumer.onboarded = False
    subscription.consumer.save()

    return subscription


def validate_subscription(subscription):
    if not subscription.active:
        return subscription

    elif subscription.payment and not _subscription_valid(subscription):
        subscription = cancel(subscription, prevent_cancelling_in_app_subscription=False)

    subscription.last_checked_at = DateUtils.now()
    subscription.save()

    return subscription


def _subscription_valid(subscription):

    if subscription.payment.apple_receipt_id or subscription.payment.google_receipt_id:
        return _in_app_subscription_valid(subscription)

    elif subscription.payment.stripe_subscription_id:
        try:
            subscription = StripeSubscription.get_subscription(subscription.payment.stripe_subscription_id)
            return subscription.status != "canceled"
        except Exception as e:
            return True

    return False


def _in_app_subscription_valid(subscription):
    valid = True

    payment = subscription.payment
    price = payment.price

    if payment.apple_receipt_id:
        try:
            InAppPayment.apple_validator(
                receipt=payment.apple_receipt_id,
                price=price,
            )
        except Exception as e:
            valid = False
            print(f"Subscription {subscription} failed to verify with error: {e}")

    elif payment.google_receipt_id:
        try:
            InAppPayment.google_validator(
                receipt=payment.google_receipt_id,
                signature=None,
                price=price,
            )
        except Exception as e:
            valid = False
            print(f"Subscription {subscription} failed to verify with error: {e}")

    return valid
