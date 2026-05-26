from .base import BaseTest

from rest_framework import status

from ...payment.models import Payment

from ..utils import Data
from ...utils import StripeSubscription


class StripeTest(BaseTest):

    def test_stripe_sca(self):
        data = Data.valid_subscription_data(self.paid_package, method="stripe")
        data["payment"]["stripe_payment_method_id"] = "pm_card_authenticationRequiredOnSetup"

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["requires_action"], True)
        self.assertIsNotNone(response.json["client_secret"])
        self.assertIsNotNone(response.json["payment_method_id"])
        self.assertIsNotNone(response.json["payment_intent_id"])

        data["payment"]["stripe_payment_method_id"] = "pm_card_authenticationRequiredOnSetup"
        data["payment"]["stripe_payment_intent_id"] = "pi_3RkBrfLBkWrwhXol0pSaYHJF"

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.subscription.refresh_from_db()

        self.assertEqual(response.json["payment"]["price"], self.paid_package.price.id)

        self.assertTrue(response.json["active"])
        self.assertIsNotNone(response.json["subscribed_at"])
        self.assertIsNone(response.json["unsubscribed_at"])

        self.assertEqual(self.subscription.package.title, "Paid")

        payment = Payment.objects.get(id=response.json["payment"]["id"])

        self.assertEqual(response.json["payment"]["method"], "stripe")
        self.assertIsNotNone(payment.stripe_subscription_id)

    def get_method(self):
        return "stripe"

    def validate_payment_active(self, payment):
        self.assertIsNotNone(payment.stripe_receipt_id)
        self.assertIsNotNone(payment.stripe_subscription_id)
        # check subscription active on stripe
        stripe_subscription = StripeSubscription.get_subscription(payment.stripe_subscription_id)
        self.assertEqual(stripe_subscription.status, "active")

    def validate_payment_inactive(self, payment):
        self.assertIsNotNone(payment.stripe_subscription_id)
        stripe_subscription = StripeSubscription.get_subscription(payment.stripe_subscription_id)
        self.assertEqual(stripe_subscription.status, "canceled")

    def validate_downgrade_error(self, response):
        # downgrades allowed
        self.assertTrue(False, "Downgrade failed on stripe when allowed")

    def can_downgrade(self):
        return True

    def invalidate_payment(self, payment):
        StripeSubscription.cancel(payment.stripe_subscription_id)

    def get_expiry_date(self, payment):
        StripeSubscription.cancel(payment.stripe_subscription_id)
        return "2025-01-01"


del BaseTest
