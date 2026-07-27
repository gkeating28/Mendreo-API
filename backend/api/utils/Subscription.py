import stripe
from rest_framework import status

from ..package.models import Package

from ..utils import InAppPayment, Exception as CustomException, DateUtils, StripeSubscription, Api


def cancel(subscription, prevent_cancelling_in_app_subscription=True):
    if subscription.active is False:
        return CustomException.raise_error(
            "Your subscription is not active.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if prevent_cancelling_in_app_subscription:
        if subscription.payment and (
            subscription.payment.apple_receipt_id or subscription.payment.google_receipt_id
        ):
            name = "Apple App Store" if subscription.payment.apple_receipt_id else "Google Play Store"
            return CustomException.raise_error(
                f"Please visit the {name} to cancel this subscription",
                status_code=status.HTTP_400_BAD_REQUEST
            )

    if subscription.payment and subscription.payment.stripe_subscription_id:
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


def activate_complimentary(subscription, package=None):
    """Activate a subscription without a payment (Stripe/Apple/Google bypass).

    Safe to call repeatedly; only writes when state needs to change.
    """
    if package is None:
        package = Package.objects.exclude(default=True).order_by("created_at").first()
        if package is None:
            package = Package.get_default()

    changed = False
    if not subscription.active:
        subscription.active = True
        subscription.subscribed_at = DateUtils.now()
        subscription.unsubscribed_at = None
        changed = True

    if subscription.payment_id is not None:
        subscription.payment = None
        changed = True

    if package and subscription.package_id != package.id:
        subscription.package = package
        subscription.title = package.title
        changed = True

    if changed:
        subscription.save()

    return subscription


def grant_complimentary_access(consumer, mark_onboarded=True):
    """Grant a consumer access without Stripe. Used by management command / bypass."""
    subscription = activate_complimentary(consumer.subscription)

    user = consumer.user
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])

    if mark_onboarded and not consumer.onboarded:
        consumer.onboarded = True
        consumer.save(update_fields=["onboarded"])
    elif not consumer.onboarded:
        consumer.update_onboarding_status()

    return subscription


def validate_subscription(subscription):
    if Api.BYPASS_SUBSCRIPTION:
        # Keep complimentary access alive while billing is disabled.
        subscription = activate_complimentary(subscription)
        subscription.last_checked_at = DateUtils.now()
        subscription.save(update_fields=["last_checked_at"])
        return subscription

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
