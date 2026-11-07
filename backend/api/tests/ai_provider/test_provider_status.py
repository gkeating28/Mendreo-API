import json
import time
from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status

from ..TestCase import TestCase
from ..utils.manager import Auth
from ...ai_provider.models import AiProvider, AiProviderAuditLog
from ...setting.models import Setting
from ...utils import Constants
from ...utils.AiProviderFactory import (
    _answerer_note,
    note_answering_provider,
    run_with_failover,
)


class ProviderStatusTest(TestCase):

    def setUp(self):
        super().setUp()
        AiProvider.objects.all().delete()
        AiProviderAuditLog.objects.all().delete()
        Setting.all_objects.filter(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).hard_delete()
        _answerer_note["provider_id"] = None
        _answerer_note["written_at"] = 0.0

        self.google = AiProvider(
            name="Google",
            provider=Constants.AI_PROVIDER_GOOGLE,
            default_model="gemini-3.1-flash-lite",
            is_default=True,
            enabled=True,
        )
        self.google.set_api_key("google-secret-key")
        self.google.save()

        self.openai = AiProvider(
            name="OpenAI",
            provider=Constants.AI_PROVIDER_OPENAI,
            default_model="gpt-4.1-mini",
            is_default=False,
            enabled=True,
        )
        self.openai.set_api_key("openai-secret-key")
        self.openai.save()

    def _status(self, access_token=None):
        return self._get(
            "/ai-providers/status",
            access_token=access_token or Auth.get_platform_admin_access_token(),
        )

    def _store_answerer(self, provider, at):
        payload = json.dumps(
            {
                "provider_id": provider.id,
                "provider_name": provider.name,
                "at": at.isoformat(),
            }
        )
        updated = Setting.all_objects.filter(
            key=Constants.SETTING_KEY_AI_LAST_ANSWERER
        ).update(value=payload, deleted_at=None)
        if not updated:
            Setting.objects.create(
                key=Constants.SETTING_KEY_AI_LAST_ANSWERER,
                value=payload,
            )

    def test_consumer_cannot_read_status(self):
        self.permission_denied_test(
            self._status(access_token=Auth.get_consumer_access_token())
        )

    def test_settings_hide_and_reject_the_answerer_row(self):
        self._store_answerer(self.openai, timezone.now())
        stored = Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value
        token = Auth.get_platform_admin_access_token()

        listed = self._get("/settings", access_token=token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertNotIn(Constants.SETTING_KEY_AI_LAST_ANSWERER, listed.json)
        self.assertIn("chat_openers", listed.json)

        rejected = self._post(
            "/settings",
            {
                "survey_enabled": False,
                Constants.SETTING_KEY_AI_LAST_ANSWERER: "edited",
            },
            access_token=token,
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value,
            stored,
        )
        self.assertTrue(self._get("/settings", access_token=token).json["survey_enabled"])

    def test_status_default_active_and_degraded(self):
        self._store_answerer(self.google, timezone.now())
        same = self._status()
        self.assertEqual(same.status_code, status.HTTP_200_OK)
        self.assertEqual(same.json["default"]["id"], self.google.id)
        self.assertEqual(same.json["default"]["default_model"], "gemini-3.1-flash-lite")
        self.assertEqual(same.json["active"]["id"], self.google.id)
        self.assertFalse(same.json["degraded"])
        self.assertNotIn("api_key", json.dumps(same.json))
        self.assertNotIn("google-secret-key", json.dumps(same.json))
        self.assertNotIn("extra_config", json.dumps(same.json))

        self._store_answerer(self.openai, timezone.now())
        shifted = self._status()
        self.assertEqual(shifted.json["active"]["id"], self.openai.id)
        self.assertEqual(shifted.json["active"]["name"], "OpenAI")
        self.assertTrue(shifted.json["degraded"])

        Setting.all_objects.filter(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).hard_delete()
        missing = self._status()
        self.assertIsNone(missing.json["active"])
        self.assertFalse(missing.json["degraded"])

    def test_stale_answerer_is_unknown_and_not_degraded(self):
        self._store_answerer(self.openai, timezone.now() - timedelta(hours=25))
        response = self._status()
        self.assertIsNone(response.json["active"])
        self.assertFalse(response.json["degraded"])

    def test_failover_counts_and_truncated_error(self):
        hidden = " https://internal.example/v1/keys sk-live-SHOULD-NOT-LEAK"
        long_error = "latest boom " + ("y" * 400) + hidden
        AiProviderAuditLog.log(
            provider=self.openai,
            action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
            detail={
                "failed_providers": [self.google.id],
                "errors": [f"{self.google.id}/google: earlier"],
            },
        )
        latest = AiProviderAuditLog.log(
            provider=self.openai,
            action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
            detail={
                "failed_providers": [self.google.id],
                "errors": [f"{self.google.id}/google: {long_error}"],
            },
        )
        stale = AiProviderAuditLog.log(
            provider=self.openai,
            action=Constants.AI_PROVIDER_AUDIT_FAILOVER,
            detail={
                "failed_providers": [self.google.id],
                "errors": [f"{self.google.id}/google: old boom"],
            },
        )
        AiProviderAuditLog.objects.filter(id=stale.id).update(
            created_at=timezone.now() - timedelta(days=2)
        )

        payload = self._status().json
        rows = {row["id"]: row for row in payload["providers"]}
        full_error = f"{self.google.id}/google: {long_error}"
        self.assertEqual(rows[self.google.id]["failure_count"], 2)
        self.assertEqual(rows[self.google.id]["failover_count"], 0)
        self.assertEqual(len(rows[self.google.id]["last_error"]), 200)
        self.assertEqual(rows[self.google.id]["last_error"], full_error[:200])
        self.assertTrue(
            rows[self.google.id]["last_error"].startswith(f"{self.google.id}/google: latest boom")
        )
        body = json.dumps(payload)
        self.assertNotIn(full_error[200:], body)
        self.assertNotIn("https://", body)
        self.assertNotIn("http://", body)
        self.assertNotIn("sk-live-SHOULD-NOT-LEAK", body)
        self.assertNotIn("google-secret-key", body)
        self.assertNotIn("openai-secret-key", body)
        for forbidden in (
            "api_key",
            "api_key_encrypted",
            "api_key_last4",
            "extra_config",
        ):
            self.assertNotIn(forbidden, body)
        self.assertEqual(
            rows[self.google.id]["last_failure_at"],
            latest.created_at.isoformat(),
        )
        self.assertEqual(rows[self.openai.id]["failover_count"], 2)
        self.assertEqual(rows[self.openai.id]["failure_count"], 0)

    def test_note_throttles_same_provider_and_writes_a_change_immediately(self):
        note_answering_provider(self.google)
        stored = json.loads(
            Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value
        )
        self.assertEqual(
            set(stored),
            {"provider_id", "provider_name", "at"},
        )
        self.assertEqual(stored["provider_id"], self.google.id)
        self.assertNotIn("google-secret-key", stored["provider_name"])

        with CaptureQueriesContext(connection) as captured:
            note_answering_provider(self.google)
        self.assertEqual(captured.captured_queries, [])
        self.assertEqual(
            Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value,
            json.dumps(stored),
        )

        note_answering_provider(self.openai)
        changed = json.loads(
            Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value
        )
        self.assertEqual(changed["provider_id"], self.openai.id)
        self.assertEqual(changed["provider_name"], "OpenAI")

        _answerer_note["written_at"] = time.monotonic() - 301
        later = timezone.now() + timedelta(minutes=6)
        with patch("django.utils.timezone.now", return_value=later):
            note_answering_provider(self.openai)
        refreshed = json.loads(
            Setting.objects.get(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).value
        )
        self.assertEqual(refreshed["provider_id"], self.openai.id)
        self.assertEqual(refreshed["at"], later.isoformat())

    def test_note_failure_does_not_break_the_reply(self):
        with patch.object(Setting.objects, "filter", side_effect=RuntimeError("db down")):
            with self.assertLogs("api.utils.AiProviderFactory", level="WARNING") as logs:
                result, provider = run_with_failover(lambda _provider: "ok")
        self.assertEqual(result, "ok")
        self.assertEqual(provider.id, self.google.id)
        self.assertTrue(any("Could not record" in line for line in logs.output))
        self.assertFalse(
            Setting.objects.filter(key=Constants.SETTING_KEY_AI_LAST_ANSWERER).exists()
        )
