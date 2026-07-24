from .base import BaseTest

from ...utils import InAppPayment

from freezegun import freeze_time


@freeze_time("2022-06-09")
class AppleTest(BaseTest):

    def get_method(self):
        return "in_app_apple"

    def validate_payment_active(self, payment):
        self.assertIsNotNone(payment.apple_receipt_id)
        self.assertIsNotNone(payment.apple_receipt_id_hash)
        self.assertEqual(payment.hash(payment.apple_receipt_id), payment.apple_receipt_id_hash)

        InAppPayment.apple_validator(payment.apple_receipt_id, payment.price)

    def validate_payment_inactive(self, payment):
        # no way to check this?
        pass

    def invalidate_payment(self, payment):
        payment.apple_receipt_id = "Made Up Apple Receipt"
        payment.save()
        return payment

    def validate_downgrade_error(self, response):
        self.assertEqual(response.json["detail"], "Please visit the Apple App Store to cancel this subscription")

    def can_downgrade(self):
        return False

    def get_expiry_date(self, payment):
        return "2025-01-01"


del BaseTest
