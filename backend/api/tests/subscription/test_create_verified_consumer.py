from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from ...tests.TestCase import TestCase
from ...tests.utils import Data
from ...user.models import User
from ...consumer.models import Consumer
from ..utils.manager import Auth


class CreateVerifiedConsumerCommandTest(TestCase):

    def test_creates_verified_consumer_with_complimentary_access(self):
        out = StringIO()
        call_command(
            "create_verified_consumer",
            "new.verified@example.com",
            "SecurePass1!",
            "--first-name",
            "Ada",
            "--last-name",
            "Lovelace",
            stdout=out,
        )

        user = User.objects.get(email="new.verified@example.com")
        self.assertTrue(user.email_verified)
        self.assertEqual(user.first_name, "Ada")
        self.assertEqual(user.last_name, "Lovelace")
        self.assertTrue(user.check_password("SecurePass1!"))

        consumer = Consumer.objects.get(user=user)
        self.assertTrue(consumer.subscription.active)
        self.assertTrue(consumer.onboarded)
        self.assertIsNone(consumer.subscription.payment_id)
        self.assertIn("Created verified consumer", out.getvalue())

    def test_existing_user_requires_update_flag(self):
        data = Data.valid_consumer_data()
        data["user"]["email"] = "existing@example.com"
        Auth.create_consumer(data=data)

        with self.assertRaises(CommandError) as ctx:
            call_command(
                "create_verified_consumer",
                "existing@example.com",
                "SecurePass1!",
            )

        self.assertIn("--update", str(ctx.exception))

    def test_update_resets_password_and_verifies(self):
        data = Data.valid_consumer_data()
        data["user"]["email"] = "update.me@example.com"
        consumer = Auth.create_consumer(data=data)
        user = consumer.user
        user.email_verified = False
        user.save(update_fields=["email_verified"])
        consumer.subscription.active = False
        consumer.subscription.save(update_fields=["active"])
        consumer.onboarded = False
        consumer.save(update_fields=["onboarded"])

        out = StringIO()
        call_command(
            "create_verified_consumer",
            "update.me@example.com",
            "NewSecurePass1!",
            "--update",
            stdout=out,
        )

        user.refresh_from_db()
        consumer.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertTrue(user.check_password("NewSecurePass1!"))
        self.assertTrue(consumer.subscription.active)
        self.assertTrue(consumer.onboarded)
        self.assertIn("Updated verified consumer", out.getvalue())
