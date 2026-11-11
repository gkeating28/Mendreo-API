"""Admin-editable app tour and generated voice clips."""

import json
from unittest.mock import patch

from django.core.cache import cache
from rest_framework import status

from ...setting.models import Setting
from ...tour.defaults import DEFAULT_TOUR_STEPS
from ...tour.services import clip_hash
from ...user.models import UserSettings
from ...utils import Api, Constants
from ...voice.elevenlabs_client import ElevenLabsRequestError, resolve_elevenlabs_voice
from ..TestCase import TestCase
from ..utils.manager import Auth

HERO = next(step for step in DEFAULT_TOUR_STEPS if step["id"] == "hero")


def _by_id(payload, step_id):
    return next(step for step in payload["steps"] if step["id"] == step_id)


class TourTests(TestCase):
    def setUp(self):
        cache.clear()
        self.consumer = Auth.create_consumer()
        self.consumer_token = Auth.get_consumer_access_token(self.consumer)
        self.admin_token = Auth.get_platform_admin_access_token()

    def _stored(self):
        setting = Setting.objects.get(key=Constants.SETTING_KEY_APP_TOUR)
        return json.loads(setting.value)

    def _seed_old_clip(self):
        setting = Setting.objects.get(key=Constants.SETTING_KEY_APP_TOUR)
        stored = json.loads(setting.value or "{}")
        stored["hero"] = {
            "audio_key": "/tour/hero-oldclip.mp3",
            "audio_hash": "not-the-current",
        }
        setting.value = json.dumps(stored)
        setting.save()

    def test_defaults_are_returned_when_nothing_is_saved(self):
        response = self._get("/tour", access_token=self.consumer_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(len(response.json["steps"]), len(DEFAULT_TOUR_STEPS))
        for default in DEFAULT_TOUR_STEPS:
            step = _by_id(response.json, default["id"])
            self.assertEqual(step["title"], default["title"])
            self.assertEqual(step["body"], default["body"])
            self.assertEqual(step["platforms"], default["platforms"])
            self.assertIsNone(step["audio_url"])
            self.assertEqual(
                set(step),
                {"id", "title", "body", "platforms", "audio_url"},
            )
        nav_main = _by_id(response.json, "nav-main")
        nav_bar = _by_id(response.json, "nav-bar")
        insights = _by_id(response.json, "progress-insights")
        account_menu = _by_id(response.json, "account-menu")
        hero = _by_id(response.json, "hero")
        ids = [step["id"] for step in response.json["steps"]]
        self.assertEqual(ids[0], "account-menu")
        self.assertEqual(account_menu["platforms"], ["web", "mobile"])
        self.assertEqual(account_menu["title"], "Your account menu")
        self.assertEqual(
            account_menu["body"],
            "Welcome to Mendreo. Click your initials up here to manage your profile, "
            "open your settings and manage your membership.",
        )
        self.assertEqual(hero["platforms"], ["mobile"])
        self.assertEqual(hero["title"], "Start where the day is")
        self.assertEqual(nav_main["platforms"], ["web"])
        self.assertEqual(nav_bar["platforms"], ["mobile"])
        self.assertEqual(insights["platforms"], ["web", "mobile"])
        mobile_ids = [
            step["id"] for step in response.json["steps"] if "mobile" in step["platforms"]
        ]
        self.assertEqual(
            mobile_ids,
            [
                "account-menu",
                "hero",
                "home-tiles",
                "nav-bar",
                "chat-practice",
                "exercise-tabs",
                "exercise-practice",
                "progress-tabs",
                "progress-feelings",
                "progress-insights",
                "progress-practice",
                "chat-intro",
            ],
        )
        self.assertEqual(insights["title"], "Your insights")
        self.assertLess(ids.index("progress-feelings"), ids.index("progress-insights"))
        self.assertLess(ids.index("progress-insights"), ids.index("progress-practice"))
        self.assertLess(ids.index("progress-practice"), ids.index("chat-intro"))
        self.assertEqual(ids[-1], "chat-intro")
        chat_intro = _by_id(response.json, "chat-intro")
        self.assertEqual(chat_intro["platforms"], ["web", "mobile"])
        self.assertEqual(chat_intro["title"], "Your first chat")
        self.assertEqual(
            chat_intro["body"],
            "We're in the chat now. This is where you and I talk. Why don't you "
            "have a go and see how you get on?",
        )
        self.assertNotIn("progress-themes", ids)

    def test_stored_progress_themes_id_is_ignored(self):
        Setting.objects.update_or_create(
            key=Constants.SETTING_KEY_APP_TOUR,
            defaults={
                "value": json.dumps({
                    "progress-themes": {
                        "title": "Themes and measures",
                        "body": "Themes are the threads running through your check-ins.",
                    },
                    "hero": {"title": "Saved hero"},
                })
            },
        )
        cache.clear()
        response = self._get("/tour", access_token=self.consumer_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        ids = [step["id"] for step in response.json["steps"]]
        self.assertNotIn("progress-themes", ids)
        self.assertEqual(_by_id(response.json, "progress-insights")["title"], "Your insights")
        self.assertEqual(_by_id(response.json, "hero")["title"], "Saved hero")

    def test_blank_fields_fall_back_to_the_default(self):
        saved = self._put(
            "/tour/config",
            {"steps": [{"id": "hero", "title": "  ", "body": ""}]},
            self.admin_token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.json)
        hero = _by_id(saved.json, "hero")
        self.assertEqual(hero["title"], HERO["title"])
        self.assertEqual(hero["body"], HERO["body"])
        consumer = self._get("/tour", access_token=self.consumer_token)
        self.assertEqual(_by_id(consumer.json, "hero")["title"], HERO["title"])

    def test_unknown_step_id_is_rejected(self):
        response = self._put(
            "/tour/config",
            {"steps": [{"id": "nope", "title": "Hello"}]},
            self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)
        self.assertIn("nope", json.dumps(response.json))
        self.assertNotIn("nope", self._stored())

        extra = self._put(
            "/tour/config",
            {"steps": [{"id": "hero", "title": "Hello", "platforms": ["web"]}]},
            self.admin_token,
        )
        self.assertEqual(extra.status_code, status.HTTP_400_BAD_REQUEST, extra.json)
        self.assertNotIn("platforms", json.dumps(self._stored()))

    def test_over_length_text_is_rejected(self):
        response = self._put(
            "/tour/config",
            {"steps": [{"id": "hero", "title": "T" * 81, "body": "B" * 501}]},
            self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)
        self.assertNotIn("T" * 81, json.dumps(self._stored()))

    def test_put_does_not_change_other_settings(self):
        before = {
            row.key: row.value
            for row in Setting.objects.exclude(key=Constants.SETTING_KEY_APP_TOUR)
        }
        response = self._put(
            "/tour/config",
            {"steps": [{"id": "chat-practice", "title": "Talk with Toni"}]},
            self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        after = {
            row.key: row.value
            for row in Setting.objects.exclude(key=Constants.SETTING_KEY_APP_TOUR)
        }
        self.assertEqual(after, before)
        self.assertEqual(_by_id(response.json, "chat-practice")["title"], "Talk with Toni")
        self.assertEqual(_by_id(response.json, "chat-practice")["body"], next(
            step["body"] for step in DEFAULT_TOUR_STEPS if step["id"] == "chat-practice"
        ))

    def test_consumer_can_read_the_tour_but_not_change_it(self):
        with patch("api.tour.services.synthesize_speech") as synthesize:
            read = self._get("/tour", access_token=self.consumer_token)
            config = self._get("/tour/config", access_token=self.consumer_token)
            update = self._put(
                "/tour/config",
                {"steps": [{"id": "hero", "title": "Nope"}]},
                self.consumer_token,
            )
            audio = self._post(
                "/tour/steps/hero/audio",
                {},
                self.consumer_token,
            )
        self.assertEqual(read.status_code, status.HTTP_200_OK, read.json)
        self.assertEqual(config.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(update.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(audio.status_code, status.HTTP_403_FORBIDDEN)
        synthesize.assert_not_called()

    def test_anonymous_gets_nothing(self):
        read = self._get("/tour")
        config = self._get("/tour/config")
        update = self._put("/tour/config", {"steps": []})
        audio = self._post("/tour/steps/hero/audio", {})
        for response in (read, config, update, audio):
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertNotIn("Welcome to Mendreo", response.content.decode())

    def test_editing_the_body_makes_the_clip_stale(self):
        self._seed_old_clip()
        with (
            patch.object(Api, "SUPABASE_STORAGE_URL", "https://cdn.example"),
            patch.object(Api, "SUPABASE_STORAGE_BUCKET", "public-bucket"),
            patch("api.tour.services.synthesize_speech", return_value=(b"mp3", "audio/mpeg")),
            patch("api.tour.services.File.upload"),
            patch("api.tour.services.File.delete"),
        ):
            created = self._post("/tour/steps/hero/audio", {}, self.admin_token)
            self.assertEqual(created.status_code, status.HTTP_200_OK, created.json)
            current_url = created.json["audio_url"]
            self.assertIn("/tour/hero-", current_url)
            self.assertFalse(created.json["audio_stale"])

            renamed = self._put(
                "/tour/config",
                {"steps": [{"id": "hero", "title": "A new title"}]},
                self.admin_token,
            )
            self.assertEqual(_by_id(renamed.json, "hero")["audio_url"], current_url)
            self.assertFalse(_by_id(renamed.json, "hero")["audio_stale"])

            edited = self._put(
                "/tour/config",
                {"steps": [{"id": "hero", "body": "A different explanation."}]},
                self.admin_token,
            )
            hero = _by_id(edited.json, "hero")
            self.assertIsNone(hero["audio_url"])
            self.assertTrue(hero["audio_exists"])
            self.assertTrue(hero["audio_stale"])

            consumer = self._get("/tour", access_token=self.consumer_token)
            shown = _by_id(consumer.json, "hero")
            self.assertIsNone(shown["audio_url"])
            self.assertNotIn("audio_exists", shown)
            self.assertNotIn("audio_stale", shown)

    def test_audio_generation_stores_the_clip_and_deletes_the_old_file(self):
        self._seed_old_clip()
        _voice_key, elevenlabs_voice_id = resolve_elevenlabs_voice(
            UserSettings.VoiceId.FEMALE_IRISH,
        )
        expected_hash = clip_hash(HERO["body"], UserSettings.VoiceId.FEMALE_IRISH)
        expected_key = f"/tour/hero-{expected_hash[:8]}.mp3"
        with (
            patch("api.tour.services.synthesize_speech", return_value=(b"mp3-bytes", "audio/mpeg")) as synthesize,
            patch("api.tour.services.File.upload") as upload,
            patch("api.tour.services.File.delete") as delete,
        ):
            response = self._post(
                "/tour/steps/hero/audio",
                {"voice_id": "female_irish"},
                self.admin_token,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        synthesize.assert_called_once_with(HERO["body"], elevenlabs_voice_id)
        upload.assert_called_once_with(
            b"mp3-bytes",
            expected_key,
            content_type="audio/mpeg",
            public=True,
        )
        delete.assert_called_once_with("/tour/hero-oldclip.mp3")
        stored = self._stored()["hero"]
        self.assertEqual(stored["audio_key"], expected_key)
        self.assertEqual(stored["audio_hash"], expected_hash)
        self.assertNotIn(HERO["body"], json.dumps({
            "detail": response.json.get("detail"),
        }))

    def test_audio_generation_failure_leaves_the_old_clip(self):
        self._seed_old_clip()
        before = Setting.objects.get(key=Constants.SETTING_KEY_APP_TOUR).value
        with (
            patch(
                "api.tour.services.synthesize_speech",
                side_effect=ElevenLabsRequestError("Could not generate speech. sk_test_secret", 502),
            ),
            patch("api.tour.services.File.upload") as upload,
            patch("api.tour.services.File.delete") as delete,
        ):
            speech_failed = self._post("/tour/steps/hero/audio", {}, self.admin_token)
        self.assertEqual(speech_failed.status_code, status.HTTP_502_BAD_GATEWAY, speech_failed.json)
        self.assertEqual(speech_failed.json["detail"], "Could not generate speech.")
        self.assertNotIn("sk_test_secret", speech_failed.content.decode())
        self.assertNotIn(HERO["body"], speech_failed.content.decode())
        upload.assert_not_called()
        delete.assert_not_called()
        self.assertEqual(Setting.objects.get(key=Constants.SETTING_KEY_APP_TOUR).value, before)

        with (
            patch("api.tour.services.synthesize_speech", return_value=(b"mp3", "audio/mpeg")),
            patch("api.tour.services.File.upload", return_value="Upload error: sk_storage_secret"),
            patch("api.tour.services.File.delete") as delete,
        ):
            store_failed = self._post("/tour/steps/hero/audio", {}, self.admin_token)
        self.assertEqual(store_failed.status_code, status.HTTP_502_BAD_GATEWAY, store_failed.json)
        self.assertEqual(store_failed.json["detail"], "Could not store the audio clip.")
        self.assertNotIn("sk_storage_secret", store_failed.content.decode())
        delete.assert_not_called()
        self.assertEqual(Setting.objects.get(key=Constants.SETTING_KEY_APP_TOUR).value, before)

    def test_empty_and_too_long_speech_are_rejected(self):
        with (
            patch("api.tour.services.synthesize_speech") as synthesize,
            patch("api.tour.services.File.upload") as upload,
            patch("api.tour.services.tour_steps", return_value=[{
                "id": "hero",
                "title": "Start where the day is",
                "body": "   ",
                "platforms": ["web", "mobile"],
                "audio_url": None,
                "audio_exists": True,
                "audio_stale": False,
            }]),
        ):
            empty = self._post("/tour/steps/hero/audio", {}, self.admin_token)
        self.assertEqual(empty.status_code, status.HTTP_400_BAD_REQUEST, empty.json)
        self.assertEqual(empty.json["detail"], "This step has no text to read.")
        synthesize.assert_not_called()
        upload.assert_not_called()

        long_body = "a" * 5001
        with (
            patch("api.tour.services.synthesize_speech") as synthesize,
            patch("api.tour.services.File.delete") as delete,
            patch("api.tour.services.tour_steps", return_value=[{
                "id": "hero",
                "title": "Start where the day is",
                "body": long_body,
                "platforms": ["web", "mobile"],
                "audio_url": None,
                "audio_exists": False,
                "audio_stale": False,
            }]),
        ):
            too_long = self._post("/tour/steps/hero/audio", {}, self.admin_token)
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST, too_long.json)
        self.assertNotIn(long_body, too_long.content.decode())
        synthesize.assert_not_called()
        delete.assert_not_called()
