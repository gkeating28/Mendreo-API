from rest_framework import status

from ...tests.TestCase import TestCase
from ...utils import Api, Subscription as SubscriptionUtils
from ..utils.manager import Auth
from ...package.models import Package


class BypassSubscriptionTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_access_token(self.consumer.user)
        self.paid_package = Package.objects.filter(title="Paid").first()
        self._original_bypass = Api.BYPASS_SUBSCRIPTION

    def tearDown(self):
        Api.BYPASS_SUBSCRIPTION = self._original_bypass

    def test_validate_activates_complimentary_when_bypass_on(self):
        Api.BYPASS_SUBSCRIPTION = True
        subscription = self.consumer.subscription
        self.assertFalse(subscription.active)

        SubscriptionUtils.validate_subscription(subscription)
        subscription.refresh_from_db()

        self.assertTrue(subscription.active)
        self.assertIsNone(subscription.payment_id)
        self.assertIsNotNone(subscription.subscribed_at)

    def test_validate_leaves_inactive_when_bypass_off(self):
        Api.BYPASS_SUBSCRIPTION = False
        subscription = self.consumer.subscription

        SubscriptionUtils.validate_subscription(subscription)
        subscription.refresh_from_db()

        self.assertFalse(subscription.active)

    def test_user_info_activates_when_bypass_on(self):
        Api.BYPASS_SUBSCRIPTION = True
        self.assertFalse(self.consumer.subscription.active)

        response = self._get("/user/info", access_token=self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.consumer.subscription.refresh_from_db()
        self.assertTrue(self.consumer.subscription.active)
        self.assertTrue(response.json["consumer"]["subscription"]["active"])

    def test_onboarding_hides_packages_when_bypass_on(self):
        Api.BYPASS_SUBSCRIPTION = True

        response = self._get("/onboarding", access_token=self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["packages"], [])
        self.consumer.subscription.refresh_from_db()
        self.assertTrue(self.consumer.subscription.active)

    def test_patch_without_payment_activates_when_bypass_on(self):
        Api.BYPASS_SUBSCRIPTION = True
        data = {"package": self.paid_package.id}

        response = self._patch(
            f"/subscriptions/{self.consumer.user_id}",
            data,
            access_token=self.consumer_access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json["active"])
        self.assertIsNone(response.json["payment"])

    def test_patch_without_payment_stays_inactive_when_bypass_off(self):
        Api.BYPASS_SUBSCRIPTION = False
        data = {"package": self.paid_package.id}

        response = self._patch(
            f"/subscriptions/{self.consumer.user_id}",
            data,
            access_token=self.consumer_access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json["active"])

    def test_grant_complimentary_access(self):
        Api.BYPASS_SUBSCRIPTION = False
        user = self.consumer.user
        user.email_verified = False
        user.save()

        SubscriptionUtils.grant_complimentary_access(self.consumer, mark_onboarded=True)

        self.consumer.refresh_from_db()
        user.refresh_from_db()

        self.assertTrue(self.consumer.subscription.active)
        self.assertTrue(self.consumer.onboarded)
        self.assertTrue(user.email_verified)
        self.assertIsNone(self.consumer.subscription.payment_id)
