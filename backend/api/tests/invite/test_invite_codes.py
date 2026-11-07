from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework import status

from ..TestCase import TestCase
from ..utils.BaseTest import BaseTest
from ..utils.manager.Auth import _grant_current_consent
from ...consumer.models import Consumer
from ...invite.access import REVOKED_DETAIL
from ...invite.models import InviteCode
from ...invite.services import (
    ALPHABET,
    GLOBAL_FAIL_KEY,
    GLOBAL_LOCK_KEY,
    INVALID_DETAIL,
    RATE_LIMIT_DETAIL,
    client_ip,
)
from ...utils.Token import create as create_token
from ...session.models import Session
from ...user.models import User
from ...utils import Constants
from ...utils.Mail import _send_email
from ...utils.risk import apply_turn_risk


class InviteCodeTests(BaseTest):
    def endpoint(self):
        return "invite-codes"

    def _create(self, count=1, label_prefix="Beta", expires_at=None, token=None):
        body = {"count": count, "label_prefix": label_prefix}
        if expires_at is not None:
            body["expires_at"] = expires_at
        return self._post(
            "/invite-codes",
            body,
            access_token=token or self.admin_one_access_token,
        )

    def _get_path(self, path, access_token):
        return TestCase._get(path, access_token=access_token)

    def _redeem(self, code, ip="10.4.4.4"):
        return self._post(
            "/invite-codes/redeem",
            {"code": code},
            REMOTE_ADDR=ip,
        )

    def test_redeem_creates_a_real_account_and_reuses_it(self):
        created = self._create()
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        display = created.json[0]["code"]

        with patch("resend.Emails.send") as send:
            first = self._redeem(f"  {display.lower()}  ")
            send.assert_not_called()

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", first.json["tokens"])
        self.assertIn("access", first.json["tokens"])
        consumer = first.json["consumer"]
        self.assertFalse(consumer["onboarded"])
        self.assertIsNone(consumer["date_of_birth"])
        self.assertTrue(consumer["consent_required"])
        self.assertTrue(consumer["subscription"]["active"])
        self.assertIsNone(consumer["subscription"]["payment"])

        user = User.objects.get(id=consumer["user"]["id"])
        self.assertTrue(user.email_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.first_name, "")
        self.assertTrue(user.email.endswith("@invite.mendreo.invalid"))
        self.assertEqual(
            user.consumer.signup_source, Constants.SIGNUP_SOURCE_INVITE_CODE
        )
        self.assertFalse(user.consumer.onboarded)
        self.assertIsNone(user.consumer.date_of_birth)

        from ...consent.models import ConsumerConsent

        self.assertFalse(ConsumerConsent.objects.filter(consumer=user.consumer).exists())

        second = self._redeem(display.replace("-", " "))
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json["consumer"]["user"]["id"], user.id)
        self.assertEqual(
            User.objects.filter(email__iendswith="@invite.mendreo.invalid").count(),
            1,
        )
        self.assertEqual(InviteCode.objects.filter(consumer__user=user).count(), 1)

        blocked = self._get_path(
            "/onboarding/status",
            access_token=f"Bearer {first.json['tokens']['access']}",
        )
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.json["detail"], Constants.CONSENT_REQUIRED_DETAIL)

        _grant_current_consent(user.consumer)
        allowed = self._get_path(
            "/onboarding/status",
            access_token=f"Bearer {first.json['tokens']['access']}",
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertFalse(allowed.json["onboarded"])
        self.assertNotIn("email", allowed.json)
        self.assertNotIn("email_verified", allowed.json)

        verify = self._post(
            "/user/request-verify-email",
            {},
            access_token=f"Bearer {first.json['tokens']['access']}",
        )
        self.assertEqual(verify.status_code, status.HTTP_204_NO_CONTENT)

    def test_unknown_expired_and_revoked_share_one_message(self):
        created = self._create(count=2, label_prefix="Guess")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        expired = InviteCode.objects.get(id=created.json[0]["id"])
        revoked = InviteCode.objects.get(id=created.json[1]["id"])
        expired.expires_at = timezone.now() - timedelta(minutes=1)
        expired.save(update_fields=["expires_at"])
        revoked.active = False
        revoked.save(update_fields=["active"])

        unknown = self._redeem("ZZZZZZZZ", ip="10.8.0.1")
        expired_response = self._redeem(created.json[0]["code"], ip="10.8.0.2")
        revoked_response = self._redeem(created.json[1]["code"], ip="10.8.0.3")

        self.assertEqual(unknown.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(expired_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(revoked_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(unknown.json["detail"], INVALID_DETAIL)
        self.assertEqual(expired_response.json["detail"], unknown.json["detail"])
        self.assertEqual(revoked_response.json["detail"], unknown.json["detail"])

    def test_rate_limit_counts_only_failures(self):
        created = self._create()
        display = created.json[0]["code"]
        ip = "10.9.9.9"

        for _ in range(9):
            response = self._redeem("NOPECODE", ip=ip)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        success = self._redeem(display, ip=ip)
        self.assertEqual(success.status_code, status.HTTP_200_OK)

        tenth = self._redeem("NOPECODE", ip=ip)
        self.assertEqual(tenth.status_code, status.HTTP_400_BAD_REQUEST)

        limited = self._redeem("NOPECODE", ip=ip)
        self.assertEqual(limited.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(limited.json["detail"], RATE_LIMIT_DETAIL)

        still_locked = self._redeem(display, ip=ip)
        self.assertEqual(still_locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_placeholder_domain_is_never_mailed(self):
        with patch("resend.Emails.send") as send:
            _send_email({
                "from": "Mendreo <noreply@example.com>",
                "to": "code-ivc_test@invite.mendreo.invalid",
                "subject": "nope",
                "html": "nope",
            })
            send.assert_not_called()

            _send_email({
                "from": "Mendreo <noreply@example.com>",
                "to": [
                    "code-ivc_test@invite.mendreo.invalid",
                    "safety@example.com",
                ],
                "subject": "alert",
                "html": "alert",
            })
            self.assertEqual(send.call_args[0][0]["to"], ["safety@example.com"])

    def test_expiry_blocks_login_refresh_and_access_tokens(self):
        created = self._create()
        redeemed = self._redeem(created.json[0]["code"], ip="10.6.6.6")
        self.assertEqual(redeemed.status_code, status.HTTP_200_OK)
        user = User.objects.get(id=redeemed.json["consumer"]["user"]["id"])
        user.set_password("a-real-password")
        user.save()

        code = InviteCode.objects.get(id=created.json[0]["id"])
        code.expires_at = timezone.now() - timedelta(seconds=5)
        code.save(update_fields=["expires_at"])

        again = self._redeem(created.json[0]["code"], ip="10.6.6.7")
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(again.json["detail"], INVALID_DETAIL)

        login = self._post(
            "/user/login",
            {"email": user.email, "password": "a-real-password"},
        )
        self.assertEqual(login.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(login.json["detail"], "This access code has expired.")

        refresh = self._post(
            "/user/refresh-token",
            {"refresh": redeemed.json["tokens"]["refresh"]},
        )
        self.assertEqual(refresh.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh.json["detail"], "This access code has expired.")

        authed = self._get_path(
            "/onboarding/status",
            access_token=f"Bearer {redeemed.json['tokens']['access']}",
        )
        self.assertEqual(authed.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(authed.json["detail"], "This access code has expired.")

    def test_revoke_cuts_off_tokens_and_reactivate_restores_them(self):
        created = self._create()
        redeemed = self._redeem(created.json[0]["code"], ip="10.6.7.1")
        user = User.objects.get(id=redeemed.json["consumer"]["user"]["id"])
        user.set_password("a-real-password")
        user.save()
        _grant_current_consent(user.consumer)
        access = f"Bearer {redeemed.json['tokens']['access']}"
        refresh = redeemed.json["tokens"]["refresh"]
        code_id = created.json[0]["id"]

        open_status = self._get_path("/onboarding/status", access)
        self.assertEqual(open_status.status_code, status.HTTP_200_OK)

        revoked = self._post(
            f"/invite-codes/{code_id}/revoke",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(revoked.status_code, status.HTTP_200_OK)
        self.assertEqual(revoked.json["status"], "revoked")

        login = self._post(
            "/user/login",
            {"email": user.email, "password": "a-real-password"},
        )
        self.assertEqual(login.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(login.json["detail"], REVOKED_DETAIL)

        refresh_blocked = self._post("/user/refresh-token", {"refresh": refresh})
        self.assertEqual(refresh_blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(refresh_blocked.json["detail"], REVOKED_DETAIL)

        access_blocked = self._get_path("/onboarding/status", access)
        self.assertEqual(access_blocked.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(access_blocked.json["detail"], REVOKED_DETAIL)

        ordinary_tokens = create_token(self.consumer_one.user)
        ordinary_refresh = self._post(
            "/user/refresh-token",
            {"refresh": ordinary_tokens["refresh"]},
        )
        self.assertEqual(ordinary_refresh.status_code, status.HTTP_200_OK)
        ordinary_status = self._get_path(
            "/onboarding/status",
            self.consumer_one_access_token,
        )
        self.assertEqual(ordinary_status.status_code, status.HTTP_200_OK)

        restored = self._post(
            f"/invite-codes/{code_id}/reactivate",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        self.assertEqual(restored.json["status"], "redeemed")

        login_again = self._post(
            "/user/login",
            {"email": user.email, "password": "a-real-password"},
        )
        self.assertEqual(login_again.status_code, status.HTTP_200_OK)

        refresh_again = self._post("/user/refresh-token", {"refresh": refresh})
        self.assertEqual(refresh_again.status_code, status.HTTP_200_OK)
        self.assertIn("access", refresh_again.json)

        access_again = self._get_path("/onboarding/status", access)
        self.assertEqual(access_again.status_code, status.HTTP_200_OK)

    def _redeem_forwarded(self, code, forwarded, proxy="100.64.0.8"):
        return self._post(
            "/invite-codes/redeem",
            {"code": code},
            REMOTE_ADDR=proxy,
            HTTP_X_FORWARDED_FOR=forwarded,
            HTTP_X_REAL_IP="198.51.100.50",
            HTTP_X_VERCEL_FORWARDED_FOR="198.51.100.9",
        )

    def test_rate_limit_counts_leftmost_forwarded_for_separately(self):
        for _ in range(10):
            response = self._redeem_forwarded("NOPECODE", "203.0.113.10, 100.64.0.8")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        other_visitor = self._redeem_forwarded("NOPECODE", "203.0.113.11, 100.64.0.8")
        self.assertEqual(other_visitor.status_code, status.HTTP_400_BAD_REQUEST)

        locked = self._redeem_forwarded("NOPECODE", "203.0.113.10, 100.64.0.8")
        self.assertEqual(locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(locked.json["detail"], RATE_LIMIT_DETAIL)

    def test_rotating_forwarded_for_stops_at_the_global_cap(self):
        cache.delete(GLOBAL_FAIL_KEY)
        cache.delete(GLOBAL_LOCK_KEY)
        self.addCleanup(cache.delete, GLOBAL_FAIL_KEY)
        self.addCleanup(cache.delete, GLOBAL_LOCK_KEY)

        created = self._create()
        display = created.json[0]["code"]

        with patch("api.invite.services.GLOBAL_FAIL_LIMIT", 3):
            for n in range(2):
                response = self._redeem_forwarded("NOPECODE", f"203.0.113.{n}")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            success = self._redeem_forwarded(display, "203.0.113.50")
            self.assertEqual(success.status_code, status.HTTP_200_OK)

            third = self._redeem_forwarded("NOPECODE", "203.0.113.3")
            self.assertEqual(third.status_code, status.HTTP_400_BAD_REQUEST)

            capped = self._redeem_forwarded("NOPECODE", "203.0.113.4")
            self.assertEqual(capped.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(capped.json["detail"], RATE_LIMIT_DETAIL)

            still_locked = self._redeem_forwarded(display, "203.0.113.99")
            self.assertEqual(still_locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(still_locked.json["detail"], RATE_LIMIT_DETAIL)

    def test_client_ip_uses_leftmost_forwarded_for(self):
        factory = RequestFactory()
        request = factory.post("/invite-codes/redeem")
        request.META["REMOTE_ADDR"] = "100.64.0.8"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.10, 100.64.0.8"
        request.META["HTTP_X_REAL_IP"] = "198.51.100.1"
        request.META["HTTP_X_VERCEL_FORWARDED_FOR"] = "198.51.100.9"
        self.assertEqual(client_ip(request), "203.0.113.10")

        del request.META["HTTP_X_FORWARDED_FOR"]
        for target in ("local", "worker", "production", "vercel"):
            with override_settings(DEPLOYMENT_TARGET=target):
                self.assertEqual(client_ip(request), "100.64.0.8")

    def test_batch_create_revoke_and_reactivate(self):
        expires = (timezone.now() + timedelta(days=14)).isoformat()
        created = self._create(count=3, label_prefix="Cohort", expires_at=expires)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(created.json), 3)

        for index, row in enumerate(created.json, start=1):
            raw = row["code"].replace("-", "")
            self.assertEqual(len(raw), 8)
            self.assertTrue(set(raw) <= set(ALPHABET))
            self.assertNotIn("0", raw)
            self.assertNotIn("O", raw)
            self.assertNotIn("1", raw)
            self.assertNotIn("I", raw)
            self.assertNotIn("L", raw)
            self.assertEqual(row["code"], f"{raw[:4]}-{raw[4:]}")
            self.assertEqual(row["label"], f"Cohort {index}")
            self.assertEqual(row["status"], "unused")
            self.assertTrue(row["active"])
            self.assertIsNone(row["account_name"])
            self.assertIsNone(row["consumer_id"])
            stored = InviteCode.objects.get(id=row["id"])
            self.assertEqual(stored.code, raw)
            self.assertEqual(stored.created_by_id, self.admin_one.user_id)

        listed = self._get_path("/invite-codes", self.admin_one_access_token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listed.json), 3)

        target = created.json[0]["id"]
        revoked = self._post(
            f"/invite-codes/{target}/revoke",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(revoked.status_code, status.HTTP_200_OK)
        self.assertEqual(revoked.json["status"], "revoked")
        self.assertFalse(revoked.json["active"])

        restored = self._post(
            f"/invite-codes/{target}/reactivate",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        self.assertEqual(restored.json["status"], "unused")
        self.assertTrue(restored.json["active"])

        too_many = self._create(count=51, label_prefix="Nope")
        self.assertEqual(too_many.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reset_refuses_a_registered_account_and_reopens_a_code_account(self):
        created = self._create(count=2, label_prefix="Reset")
        registered = InviteCode.objects.get(id=created.json[0]["id"])
        registered.consumer = self.consumer_one
        registered.redeemed_at = timezone.now()
        registered.save(update_fields=["consumer", "redeemed_at"])

        refused = self._post(
            f"/invite-codes/{registered.id}/reset",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            refused.json["detail"],
            "This account was not created from an access code.",
        )
        self.consumer_one.refresh_from_db()
        self.assertIsNone(self.consumer_one.user.deleted_at)
        registered.refresh_from_db()
        self.assertEqual(registered.consumer_id, self.consumer_one.pk)

        redeemed = self._redeem(created.json[1]["code"], ip="10.7.7.1")
        user_id = redeemed.json["consumer"]["user"]["id"]
        old_email = User.objects.get(id=user_id).email

        reset = self._post(
            f"/invite-codes/{created.json[1]['id']}/reset",
            {},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(reset.status_code, status.HTTP_200_OK)
        self.assertEqual(reset.json["status"], "unused")
        self.assertIsNone(reset.json["consumer_id"])
        self.assertIsNone(reset.json["redeemed_at"])

        old_user = User.objects.get(id=user_id)
        self.assertIsNotNone(old_user.deleted_at)
        self.assertEqual(old_user.status, Constants.USER_STATUS_SUSPENDED)
        self.assertNotEqual(old_user.email, old_email)
        self.assertTrue(old_user.email.endswith(".invalid"))
        self.assertFalse(Consumer.objects.filter(user_id=user_id).exists())

        again = self._redeem(created.json[1]["code"], ip="10.7.7.2")
        self.assertEqual(again.status_code, status.HTTP_200_OK)
        self.assertNotEqual(again.json["consumer"]["user"]["id"], user_id)

    def test_non_admins_cannot_manage_codes(self):
        created = self._create()
        code_id = created.json[0]["id"]
        token = self.consumer_one_access_token

        for path in (
            "/invite-codes",
            f"/invite-codes/{code_id}/revoke",
            f"/invite-codes/{code_id}/reactivate",
            f"/invite-codes/{code_id}/reset",
        ):
            response = self._post(path, {"count": 1, "label_prefix": "X"}, access_token=token)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, path)

        listed = self._get_path("/invite-codes", token)
        self.assertEqual(listed.status_code, status.HTTP_403_FORBIDDEN)

    def test_trust_and_safety_still_fires_for_a_code_account(self):
        created = self._create()
        redeemed = self._redeem(created.json[0]["code"], ip="10.5.5.5")
        user = User.objects.get(id=redeemed.json["consumer"]["user"]["id"])
        session = Session.objects.create(consumer=user.consumer)

        with patch("api.tasks.notify_trust_and_safety") as notify:
            apply_turn_risk(session, "I want to end my life", Constants.LIVE_RISK_LEVEL_HIGH)

        notify.delay_on_commit.assert_called_once_with(session.id)
