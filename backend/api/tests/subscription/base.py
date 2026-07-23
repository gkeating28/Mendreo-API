from ...tests.TestCase import TestCase
from abc import ABC, abstractmethod


from rest_framework import status

from ...package.models import Package
from ...payment.models import Payment

from ..utils import Data
from ..utils.manager import Auth, General

from ...utils import Api

from ...tasks import check_subscriptions

from freezegun import freeze_time

RECEIPT_PAYMENT_KEYS = {
    "stripe": "stripe_payment_method_id",
    "in_app_apple": "apple_receipt_id",
    "in_app_google": "google_receipt_id",
}

RECEIPT_ERROR_KEYS = {
    "stripe": "stripe_payment_intent_id",
    "in_app_apple": "apple_receipt_id",
    "in_app_google": "google_receipt_id",
}

BUNDLE_ID_IOS = Api.BUNDLE_ID_IOS
BUNDLE_ID_ANDROID = Api.BUNDLE_ID_ANDROID


class BaseTest(TestCase, ABC):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_access_token(self.consumer.user)

        self.subscription = self.consumer.subscription

        self.default_package = Package.objects.filter(default=True).first()
        self.paid_package = Package.objects.filter(title="Paid").first()

        self.assertFalse(self.subscription.active)

        # removes .dev from bundle id so validation is forced
        Api.BUNDLE_ID_IOS = "mendreo"
        Api.BUNDLE_ID_ANDROID = "mendreo"

    def tearDown(self):
        Api.BUNDLE_ID_IOS = BUNDLE_ID_IOS
        Api.BUNDLE_ID_ANDROID = BUNDLE_ID_ANDROID

    def _get(self, id, access_token="", **kwargs):
        response = super()._get(f"/subscriptions/{id}", access_token=access_token)

        return response

    def _patch(self, id_, data, access_token="", **kwargs):
        return super()._patch(f"/subscriptions/{id_}", data, access_token)

    def _delete(self, id_, access_token="", **kwargs):
        return super()._delete(f"/subscriptions/{id_}", access_token)

    def test_upgrade(self):
        data = Data.valid_subscription_data(self.paid_package, method=self.get_method())

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.subscription.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["payment"]["price"]["id"], self.paid_package.price.id)

        self.assertTrue(response.json["active"])
        self.assertIsNotNone(response.json["subscribed_at"])
        self.assertIsNone(response.json["unsubscribed_at"])

        self.assertEqual(self.subscription.package.title, "Paid")

        payment = Payment.objects.get(id=response.json["payment"]["id"])

        self.assertEqual(response.json["payment"]["method"], self.get_method())
        self.validate_payment_active(payment)

    def test_downgrade(self):
        data = Data.valid_subscription_data(self.paid_package, method=self.get_method())

        upgrade_response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.subscription.refresh_from_db()

        payment = self.subscription.payment

        self.assertEqual(upgrade_response.status_code, status.HTTP_200_OK)

        self.assertEqual(upgrade_response.json["payment"]["price"]["id"], self.paid_package.price.id)

        self.assertTrue(upgrade_response.json["active"])
        self.assertEqual(upgrade_response.json["payment"]["method"], self.get_method())

        self.validate_payment_active(self.subscription.payment)

        downgrade_response = self._delete(self.consumer.user_id, self.consumer_access_token)

        if not self.can_downgrade():
            self.assertEqual(downgrade_response.status_code, status.HTTP_400_BAD_REQUEST)
            self.validate_downgrade_error(downgrade_response)
            return

        self.assertEqual(downgrade_response.status_code, status.HTTP_204_NO_CONTENT)

        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.unsubscribed_at)

        self.validate_payment_inactive(payment)

    def test_duplicate(self):
        data = Data.valid_subscription_data(self.paid_package, method=self.get_method())

        upgrade_response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.subscription.refresh_from_db()

        payment = self.subscription.payment

        self.assertEqual(upgrade_response.status_code, status.HTTP_200_OK)

        self.validate_payment_active(self.subscription.payment)

        consumer = Auth.create_consumer()

        # try upgrading with previous receipt data
        if self.get_method() == "stripe":
            data["payment"]["stripe_payment_intent_id"] = payment.stripe_receipt_id

        duplicate_upgrade_response = self._patch(consumer.user_id, data, Auth.get_consumer_access_token(consumer))

        self.assertEqual(duplicate_upgrade_response.status_code, status.HTTP_400_BAD_REQUEST)

        error_key = RECEIPT_ERROR_KEYS[self.get_method()]
        self.assertEqual(
            duplicate_upgrade_response.json[error_key][0],
            "A subscription with this receipt already exists. Please contact support for assistance"
        )

    def test_resubscribe(self):
        data = Data.valid_subscription_data(self.paid_package, method=self.get_method())

        upgrade_response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.subscription.refresh_from_db()

        payment = self.subscription.payment

        self.assertEqual(upgrade_response.status_code, status.HTTP_200_OK)

        self.invalidate_payment(payment)

        check_subscriptions()

        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertTrue(self.subscription.package_id, self.default_package.id)

        resubscribe_data = Data.valid_subscription_data(self.paid_package, method=self.get_method())

        resubscribe_response = self._patch(self.consumer.user_id, resubscribe_data, self.consumer_access_token)

        self.assertEqual(resubscribe_response.status_code, status.HTTP_200_OK)

        self.subscription.refresh_from_db()
        self.validate_payment_active(self.subscription.payment)

        self.assertEqual(Payment.all_objects.filter(consumer=self.subscription.consumer).count(), 2)

    def test_with_missing_data(self):
        data = {}

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["package"][0], "This field is required.")

        data = {
            "package": self.paid_package.id,
            "payment": {}
        }

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["payment"]["details"][0], 'invalid details provided')

        data = {
            "package": self.paid_package.id,
            "payment": {
                RECEIPT_PAYMENT_KEYS[self.get_method()]: None
            }
        }

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["payment"]["details"][0], 'invalid details provided')

    def test_active_after_cron_check(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        check_subscriptions()

        self.subscription.refresh_from_db()

        self.assertTrue(self.subscription.active)
        self.assertIsNotNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_active_after_user_info_check(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        self.subscription.last_checked_at = None
        self.subscription.save()

        response = super()._get(f"/user/info", access_token=self.consumer_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.subscription.refresh_from_db()

        self.assertTrue(self.subscription.active)
        self.assertIsNotNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_canceled_after_cron_check_with_bad_payment(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        self.invalidate_payment(self.subscription.payment)

        check_subscriptions()

        self.subscription.refresh_from_db()

        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_canceled_after_user_info_check_with_bad_payment(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        self.invalidate_payment(self.subscription.payment)

        response = super()._get(f"/user/info", access_token=self.consumer_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.subscription.refresh_from_db()

        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_canceled_after_cron_check_with_expired_payment(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        with freeze_time(self.get_expiry_date(self.subscription.payment)):
            check_subscriptions()

        self.subscription.refresh_from_db()

        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_canceled_after_user_info_check_with_expired_payment(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.active)

        with freeze_time(self.get_expiry_date(self.subscription.payment)):
            response = super()._get(f"/user/info", access_token=Auth.get_consumer_access_token(self.consumer))
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.subscription.refresh_from_db()

        self.assertFalse(self.subscription.active)
        self.assertIsNone(self.subscription.payment)
        self.assertIsNotNone(self.subscription.last_checked_at)

    def test_get_with_inactive_subscription(self):
        response = self._get(self.consumer.user_id, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertFalse(response.json["active"])
        self.assertEqual(response.json["consumer"], self.consumer.user_id)

        self.assertIsNotNone(response.json["subscribed_at"])
        self.assertIsNone(response.json["unsubscribed_at"])
        self.assertIsNone(response.json["payment"])

    def test_get_with_active_subscription(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        response = self._get(self.consumer.user_id, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue(response.json["active"])
        self.assertEqual(response.json["consumer"], self.consumer.user_id)

        self.assertIsNotNone(response.json["subscribed_at"])
        self.assertIsNone(response.json["unsubscribed_at"])
        self.assertIsNotNone(response.json["payment"])
        self.assertIsNotNone(response.json["payment"]["price"])
        self.assertEqual(response.json["payment"]["method"], self.get_method())

    def test_get_with_subscription_belongs_to_someone_else(self):
        consumer = Auth.create_consumer()

        response = self._get(consumer.user_id, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["consumer"], self.consumer.user_id)

    def test_fail_already_subscribed_to_package(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        data = {
            "package": self.paid_package.id,
        }

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["subscription"][0], 'You already have a subscription for this package')

    def test_fail_with_switching_package_without_cancellation(self):
        General.subscribe_to_paid_package(self.consumer, method=self.get_method())

        data = {
            "package": self.default_package.id,
        }

        response = self._patch(self.consumer.user_id, data, self.consumer_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["subscription"][0], 'Please cancel your existing subscription first')

    def test_fail_get_with_invalid_id(self):
        response = self._get(999999, self.consumer_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["consumer"], self.consumer.user_id)

    def test_fail_get_with_admin_account(self):
        self.permission_denied_test(self._get(self.consumer.user_id, Auth.get_platform_admin_access_token()))

    def test_fail_get_with_unauthorized_account(self):
        self.unauthorized_account_test(self._get(self.consumer.user_id, ""))

    def test_fail_edit_with_admin_account(self):
        data = Data.valid_subscription_data(method=self.get_method())
        self.permission_denied_test(self._patch(self.consumer.user_id, data, Auth.get_platform_admin_access_token()))

    def test_fail_edit_with_unauthorized_account(self):
        data = Data.valid_subscription_data(method=self.get_method())
        self.unauthorized_account_test(self._patch(self.consumer.user_id, data, ""))

    @abstractmethod
    def get_method(self):
        pass

    @abstractmethod
    def validate_payment_active(self, payment):
        pass

    @abstractmethod
    def validate_payment_inactive(self, payment):
        pass

    @abstractmethod
    def invalidate_payment(self, payment):
        pass

    @abstractmethod
    def validate_downgrade_error(self, response):
        pass

    @abstractmethod
    def can_downgrade(self):
        pass

    @abstractmethod
    def get_expiry_date(self, payment):
        pass
