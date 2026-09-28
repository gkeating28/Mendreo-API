import os
from unittest.mock import patch

from rest_framework.exceptions import APIException

from ...session.models import Session
from ...setting.models import Setting
from ...user.models import User
from ...utils import Api, Constants
from ...utils.Mail import (
    _send_email,
    send_account_verification_code,
    send_code,
    send_trust_and_safety_alert,
)
from ..TestCase import TestCase
from .manager import Auth


class MailTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.user = User.objects.get(id=self.consumer.user_id)

    def _patch_send(self, **kwargs):
        return patch("resend.Emails.send", **kwargs)

    def test_verification_email_uses_resend(self):
        with patch.object(Api, "EMAIL_FROM", "noreply@example.com"), \
             patch.object(Api, "RESEND_API_KEY", "re_test_key"), \
             self._patch_send(return_value={"id": "email_1"}) as send:
            send_account_verification_code(self.user.id)

        self.user.refresh_from_db()
        code = str(self.user.verification_code)
        self.assertEqual(len(code), 4)
        self.assertTrue(code.isdigit())
        send.assert_called_once_with({
            "from": f"{Constants.APP_NAME} <noreply@example.com>",
            "to": [self.user.email],
            "subject": "Account Verification",
            "html": f"Hi {self.user.first_name},<br><br><b>{code}</b> is your account verification code",
        })

    def test_password_reset_email_uses_resend(self):
        with patch.object(Api, "EMAIL_FROM", "noreply@example.com"), \
             patch.object(Api, "RESEND_API_KEY", "re_test_key"), \
             self._patch_send(return_value={"id": "email_2"}) as send:
            send_code(self.user.id)

        self.user.refresh_from_db()
        code = str(self.user.verification_code)
        self.assertEqual(len(code), 4)
        send.assert_called_once_with({
            "from": f"{Constants.APP_NAME} <noreply@example.com>",
            "to": [self.user.email],
            "subject": "Password Reset Request",
            "html": f"Hi {self.user.first_name},<br><br><b>{code}</b> is your password reset code",
        })

    def test_trust_and_safety_alert_uses_the_same_send_path(self):
        address = Setting.get_or_create_trust_and_safety_email()
        address.value = "safety@example.com"
        address.save()
        session = Session.objects.create(consumer=self.consumer)
        leaked = "the user said something private that must not be emailed"

        with patch.object(Api, "EMAIL_FROM", "noreply@example.com"), \
             patch.object(Api, "RESEND_API_KEY", "re_test_key"), \
             self._patch_send(return_value={"id": "email_3"}) as send:
            send_trust_and_safety_alert(session.id)

        send.assert_called_once()
        payload = send.call_args.args[0]
        self.assertEqual(payload["from"], f"{Constants.APP_NAME} <noreply@example.com>")
        self.assertEqual(payload["to"], ["safety@example.com"])
        self.assertEqual(payload["subject"], "High-risk session needs review")
        self.assertIn(session.id, payload["html"])
        self.assertIn(str(self.consumer.user_id), payload["html"])
        self.assertIn("The message text is not included in this email.", payload["html"])
        self.assertNotIn(leaked, payload["html"])

    def test_trust_and_safety_skips_send_when_address_is_blank(self):
        address = Setting.get_or_create_trust_and_safety_email()
        address.value = ""
        address.save()
        session = Session.objects.create(consumer=self.consumer)

        with self._patch_send() as send:
            send_trust_and_safety_alert(session.id)

        send.assert_not_called()

    def test_empty_api_key_raises_without_logging_a_key(self):
        secret = "re_test_do_not_log"
        mail = {
            "from": "Mendreo <noreply@example.com>",
            "to": "ada@example.com",
            "subject": "Account Verification",
            "html": "Hi Ada,<br><br><b>1234</b> is your account verification code",
        }

        with patch.object(Api, "RESEND_API_KEY", ""), \
             patch.dict(os.environ, {"GENERAL_DEBUG": "False"}), \
             self._patch_send(side_effect=RuntimeError("unauthorized")) as send, \
             patch("builtins.print") as printed:
            with self.assertRaises(APIException):
                _send_email(mail)

        send.assert_called_once()
        logged = str(printed.call_args_list)
        self.assertNotIn(secret, logged)
        self.assertNotIn("RESEND_API_KEY", logged)

        with patch.object(Api, "RESEND_API_KEY", secret), \
             patch.dict(os.environ, {"GENERAL_DEBUG": "False"}), \
             self._patch_send(side_effect=RuntimeError("unauthorized")) as send, \
             patch("builtins.print") as printed:
            with self.assertRaises(APIException) as caught:
                _send_email(mail)

        send.assert_called_once()
        logged = str(printed.call_args_list) + str(caught.exception.detail)
        self.assertNotIn(secret, logged)
