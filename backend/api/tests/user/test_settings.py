from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import Auth
from ...tests.TestCase import TestCase
from ...user.models import UserSettings


class UserSettingsApiTests(BaseTest):
    def endpoint(self):
        return "user/settings"

    def _get_settings(self, access_token=""):
        return TestCase._get("/user/settings", access_token=access_token)

    def _patch_settings(self, data, access_token=""):
        return TestCase._patch("/user/settings", data, access_token=access_token)

    def test_get_returns_defaults_for_current_user(self):
        response = self._get_settings(self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(
            response.json,
            {
                "timezone": "UTC",
                "notification_push_enabled": True,
                "notification_daily_reminder_enabled": False,
                "notification_daily_reminder_time": None,
                "chat_text_size": "medium",
                "chat_speed": "normal",
                "voice_id": "female_irish",
            },
        )

    def test_patch_timezone_and_notification_fields(self):
        response = self._patch_settings(
            {
                "timezone": "Europe/Dublin",
                "notification_push_enabled": False,
                "notification_daily_reminder_enabled": True,
                "notification_daily_reminder_time": "08:30",
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["timezone"], "Europe/Dublin")
        self.assertFalse(response.json["notification_push_enabled"])
        self.assertTrue(response.json["notification_daily_reminder_enabled"])
        self.assertEqual(response.json["notification_daily_reminder_time"], "08:30:00")

        stored = UserSettings.objects.get(user=self.consumer_one.user)
        self.assertEqual(stored.timezone, "Europe/Dublin")
        self.assertFalse(stored.notification_push_enabled)
        self.assertTrue(stored.notification_daily_reminder_enabled)
        self.assertEqual(stored.notification_daily_reminder_time.strftime("%H:%M:%S"), "08:30:00")

    def test_patch_is_partial(self):
        self._patch_settings(
            {"timezone": "America/New_York"},
            self.consumer_one_access_token,
        )
        response = self._patch_settings(
            {"notification_push_enabled": False},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["timezone"], "America/New_York")
        self.assertFalse(response.json["notification_push_enabled"])
        self.assertFalse(response.json["notification_daily_reminder_enabled"])
        self.assertIsNone(response.json["notification_daily_reminder_time"])
        self.assertEqual(response.json["chat_text_size"], "medium")
        self.assertEqual(response.json["chat_speed"], "normal")
        self.assertEqual(response.json["voice_id"], "female_irish")

    def test_patch_chat_text_size_and_speed(self):
        response = self._patch_settings(
            {
                "chat_text_size": "xlarge",
                "chat_speed": "instant",
            },
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["chat_text_size"], "xlarge")
        self.assertEqual(response.json["chat_speed"], "instant")
        self.assertEqual(response.json["timezone"], "UTC")

        stored = UserSettings.objects.get(user=self.consumer_one.user)
        self.assertEqual(stored.chat_text_size, "xlarge")
        self.assertEqual(stored.chat_speed, "instant")

    def test_invalid_chat_prefs_rejected(self):
        size = self._patch_settings(
            {"chat_text_size": "huge"},
            self.consumer_one_access_token,
        )
        self.assertEqual(size.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("chat_text_size", size.json)

        speed = self._patch_settings(
            {"chat_speed": "turbo"},
            self.consumer_one_access_token,
        )
        self.assertEqual(speed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("chat_speed", speed.json)

    def test_can_clear_reminder_time(self):
        self._patch_settings(
            {"notification_daily_reminder_time": "09:00:00"},
            self.consumer_one_access_token,
        )
        response = self._patch_settings(
            {"notification_daily_reminder_time": None},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertIsNone(response.json["notification_daily_reminder_time"])

    def test_patch_voice_id(self):
        response = self._patch_settings(
            {"voice_id": "male_irish"},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["voice_id"], "male_irish")
        self.assertEqual(response.json["timezone"], "UTC")
        self.assertNotIn("elevenlabs_voice_id", response.json)

        stored = UserSettings.objects.get(user=self.consumer_one.user)
        self.assertEqual(stored.voice_id, "male_irish")

    def test_patch_new_voice_ids(self):
        for voice_id in (
            "american_male",
            "american_female",
            "british_female",
            "british_male",
        ):
            response = self._patch_settings(
                {"voice_id": voice_id},
                self.consumer_one_access_token,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
            self.assertEqual(response.json["voice_id"], voice_id)
            stored = UserSettings.objects.get(user=self.consumer_one.user)
            self.assertEqual(stored.voice_id, voice_id)

    def test_invalid_voice_id_rejected(self):
        response = self._patch_settings(
            {"voice_id": "female_american"},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("voice_id", response.json)

    def test_invalid_timezone_rejected(self):
        response = self._patch_settings(
            {"timezone": "Not/AZone"},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("timezone", response.json)

    def test_users_only_see_their_own_settings(self):
        other = Auth.create_consumer()
        other_token = Auth.get_access_token(other.user)

        self._patch_settings({"timezone": "Europe/London"}, self.consumer_one_access_token)
        self._patch_settings({"timezone": "Pacific/Auckland"}, other_token)

        mine = self._get_settings(self.consumer_one_access_token)
        theirs = self._get_settings(other_token)

        self.assertEqual(mine.json["timezone"], "Europe/London")
        self.assertEqual(theirs.json["timezone"], "Pacific/Auckland")

    def test_unauthenticated_rejected(self):
        self.unauthorized_account_test(self._get_settings())
        self.unauthorized_account_test(self._patch_settings({"timezone": "UTC"}))
