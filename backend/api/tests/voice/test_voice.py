import hashlib
import hmac
import json
import time
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from ...message.models import Message
from ...participant.models import Participant
from ...tests.TestCase import TestCase
from ...utils.Agent import GeneralResponse
from ...user.models import UserSettings
from ...voice.elevenlabs_client import (
    DEFAULT_TTS_MODEL_ID,
    DEFAULT_VOICE_ID,
    VOICE_LIBRARY_IDS,
    resolve_elevenlabs_voice,
)
from ...voice.models import VoiceGrant, hash_grant_token
from ...voice.services import VOICE_PREVIEW_TEXT
from ..utils.manager import Auth, General

LLM_SECRET = "test-elevenlabs-llm-secret"
WEBHOOK_SECRET = "test-elevenlabs-webhook-secret"
VOICE_TOKEN_PATH = "/voice/token"
VOICE_TTS_PATH = "/voice/tts"
VOICE_PREVIEW_PATH = "/voice/preview"
CHAT_COMPLETIONS_PATH = "/internal/elevenlabs/v1/chat/completions"
WEBHOOK_PATH = "/internal/elevenlabs/webhook"


class VoiceMappingTests(SimpleTestCase):
    def test_resolves_saved_keys_and_falls_back(self):
        expected = {
            "male_irish": "RlSVB64yXMZJjq67jbB1",
            "female_irish": "3b8fXc91YHS1i2DYAlBQ",
            "american_male": "TWutjvRaJqAX89preB4e",
            "american_female": "gJx1vCzNCD1EQHT212Ls",
            "british_female": "aj0fZfXTBc7E3By4X8L2",
            "british_male": "av1BMOR1GPgThz9p4fLo",
        }
        self.assertEqual(VOICE_LIBRARY_IDS, expected)
        for key, library_id in expected.items():
            self.assertEqual(resolve_elevenlabs_voice(key), (key, library_id))
        self.assertEqual(
            resolve_elevenlabs_voice(None),
            (DEFAULT_VOICE_ID, VOICE_LIBRARY_IDS["female_irish"]),
        )
        self.assertEqual(
            resolve_elevenlabs_voice("female_american"),
            (DEFAULT_VOICE_ID, VOICE_LIBRARY_IDS["female_irish"]),
        )
        self.assertEqual(VOICE_PREVIEW_TEXT, "Hi, I'm Toni. How are you feeling today?")


class EnsureTtsVoiceOverrideTests(SimpleTestCase):
    def setUp(self):
        from api.voice.elevenlabs_client import reset_tts_voice_override_cache

        reset_tts_voice_override_cache()

    @override_settings(
        ELEVENLABS_API_KEY="sk_test",
        ELEVENLABS_AGENT_ID="agent_abc",
        ELEVENLABS_API_BASE="https://api.elevenlabs.io",
    )
    @mock.patch("api.voice.elevenlabs_client.requests.patch")
    @mock.patch("api.voice.elevenlabs_client.requests.get")
    def test_skips_patch_when_already_enabled(self, get, patch):
        from api.voice.elevenlabs_client import ensure_tts_voice_override

        get.return_value = mock.Mock(
            ok=True,
            json=lambda: {
                "platform_settings": {
                    "overrides": {"conversation_config_override": {"tts": {"voice_id": True}}}
                }
            },
            text="",
        )
        ensure_tts_voice_override("sk_test", "agent_abc")
        get.assert_called_once()
        patch.assert_not_called()
        ensure_tts_voice_override("sk_test", "agent_abc")
        self.assertEqual(get.call_count, 1)

    @override_settings(
        ELEVENLABS_API_KEY="sk_test",
        ELEVENLABS_AGENT_ID="agent_abc",
        ELEVENLABS_API_BASE="https://api.elevenlabs.io",
    )
    @mock.patch("api.voice.elevenlabs_client.requests.patch")
    @mock.patch("api.voice.elevenlabs_client.requests.get")
    def test_enables_voice_id_override(self, get, patch):
        from api.voice.elevenlabs_client import ensure_tts_voice_override

        get.return_value = mock.Mock(ok=True, json=lambda: {"platform_settings": {}}, text="")
        patch.return_value = mock.Mock(ok=True, status_code=200, text="")
        ensure_tts_voice_override("sk_test", "agent_abc")
        patch.assert_called_once()
        payload = patch.call_args.kwargs["json"]
        self.assertTrue(
            payload["platform_settings"]["overrides"]["conversation_config_override"]["tts"][
                "voice_id"
            ]
        )


def _sign_webhook(body: bytes, secret: str, ts: int | None = None) -> str:
    timestamp = str(ts if ts is not None else int(time.time()))
    payload = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v0={digest}"


def _sse_body(response) -> str:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content).decode("utf-8")
    return response.content.decode("utf-8")


def _sse_contents(body: str) -> list[str]:
    texts = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            continue
        chunk = json.loads(payload)
        content = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
        if content:
            texts.append(content)
    return texts


_PROBE_BOOL_KEYS = {
    "settings_api_key",
    "settings_agent_id",
    "environ_api_key",
    "environ_agent_id",
    "configured",
    "agent_id_quoted",
}
_PROBE_KEYS = _PROBE_BOOL_KEYS | {
    "railway_service_id",
    "railway_deployment_id",
    "agent_id_kind",
    "agent_id_length",
    "api_key_kind",
    "api_base_host",
}


class ElevenLabsConfigProbeTests(TestCase):
    @override_settings(ELEVENLABS_API_KEY="", ELEVENLABS_AGENT_ID="")
    def test_reports_missing_settings(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(set(response.json), _PROBE_KEYS)
        for key in _PROBE_BOOL_KEYS:
            self.assertIsInstance(response.json[key], bool, key)
        self.assertFalse(response.json["settings_api_key"])
        self.assertFalse(response.json["settings_agent_id"])
        self.assertFalse(response.json["configured"])
        self.assertIsInstance(response.json["railway_service_id"], str)
        self.assertIsInstance(response.json["railway_deployment_id"], str)
        self.assertFalse(response.json["agent_id_quoted"])
        self.assertEqual(response.json["agent_id_kind"], "missing")
        self.assertEqual(response.json["agent_id_length"], 0)
        self.assertEqual(response.json["api_key_kind"], "missing")
        self.assertIsInstance(response.json["api_base_host"], str)

    @mock.patch.dict(
        "api.voice.elevenlabs_client.os.environ",
        {
            "RAILWAY_SERVICE_ID": "svc-from-dashboard",
            "RAILWAY_DEPLOYMENT_ID": "dpl-from-dashboard",
        },
        clear=False,
    )
    def test_reports_railway_ids_from_environ(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["railway_service_id"], "svc-from-dashboard")
        self.assertEqual(response.json["railway_deployment_id"], "dpl-from-dashboard")

    @override_settings(ELEVENLABS_API_KEY="sk-test", ELEVENLABS_AGENT_ID="agent-test")
    def test_reports_settings_present_without_values(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["settings_api_key"])
        self.assertTrue(response.json["settings_agent_id"])
        self.assertTrue(response.json["configured"])
        dumped = json.dumps(response.json)
        self.assertNotIn("sk-test", dumped)
        self.assertNotIn("agent-test", dumped)
        self.assertEqual(response.json["agent_id_kind"], "other")
        self.assertEqual(response.json["agent_id_length"], 10)
        self.assertEqual(response.json["api_key_kind"], "other")
        self.assertFalse(response.json["agent_id_quoted"])

    @override_settings(ELEVENLABS_API_KEY="  ", ELEVENLABS_AGENT_ID="agent-test")
    def test_whitespace_api_key_counts_as_missing(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertFalse(response.json["settings_api_key"])
        self.assertTrue(response.json["settings_agent_id"])
        self.assertFalse(response.json["configured"])

    @override_settings(ELEVENLABS_API_KEY='"sk_test"', ELEVENLABS_AGENT_ID='"agent_abc"')
    def test_quoted_agent_id_is_cleaned_in_probe(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["configured"])
        self.assertTrue(response.json["agent_id_quoted"])
        self.assertEqual(response.json["agent_id_kind"], "agent")
        self.assertEqual(response.json["agent_id_length"], 9)
        self.assertEqual(response.json["api_key_kind"], "sk")
        dumped = json.dumps(response.json)
        self.assertNotIn("agent_abc", dumped)
        self.assertNotIn("sk_test", dumped)

    @override_settings(ELEVENLABS_API_KEY="key_abc123", ELEVENLABS_AGENT_ID="agent_abc")
    def test_reports_api_key_id_without_value(self):
        response = self._get("/healthz/elevenlabs")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["configured"])
        self.assertEqual(response.json["api_key_kind"], "key_id")
        dumped = json.dumps(response.json)
        self.assertNotIn("key_abc123", dumped)


class MintConversationCredentialsTests(TestCase):
    @override_settings(
        ELEVENLABS_API_KEY='"sk_test"',
        ELEVENLABS_AGENT_ID='"agent_abc"',
        ELEVENLABS_API_BASE="https://api.elevenlabs.io",
    )
    @mock.patch("api.voice.elevenlabs_client.ensure_tts_voice_override")
    @mock.patch("api.voice.elevenlabs_client.requests.get")
    def test_strips_quotes_and_forwards_elevenlabs_detail(self, get, _ensure):
        from api.voice.elevenlabs_client import (
            ElevenLabsRequestError,
            mint_conversation_credentials,
        )

        signed = mock.Mock(ok=False, status_code=400, text='{"detail":{"message":"invalid agent_id"}}')
        signed.json.return_value = {"detail": {"message": "invalid agent_id", "param": "agent_id"}}
        token = mock.Mock(
            ok=False,
            status_code=400,
            text='{"detail":[{"msg":"String should match pattern","loc":["query","agent_id"]}]}',
        )
        token.json.return_value = {
            "detail": [{"msg": "String should match pattern", "loc": ["query", "agent_id"]}]
        }
        get.side_effect = [signed, token]

        with self.assertRaises(ElevenLabsRequestError) as ctx:
            mint_conversation_credentials()

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("invalid agent_id", str(ctx.exception))
        self.assertIn("String should match pattern", str(ctx.exception))
        self.assertEqual(get.call_count, 2)
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["params"]["agent_id"], "agent_abc")
            self.assertEqual(call.kwargs["headers"]["xi-api-key"], "sk_test")

    @override_settings(ELEVENLABS_API_KEY="key_not_a_secret", ELEVENLABS_AGENT_ID="agent_abc")
    @mock.patch("api.voice.elevenlabs_client.ensure_tts_voice_override")
    @mock.patch("api.voice.elevenlabs_client.requests.get")
    def test_rejects_api_key_id_without_calling_elevenlabs(self, get, ensure):
        from api.voice.elevenlabs_client import (
            ElevenLabsConfigError,
            mint_conversation_credentials,
        )

        with self.assertRaises(ElevenLabsConfigError) as ctx:
            mint_conversation_credentials()

        self.assertIn("sk_…", str(ctx.exception))
        get.assert_not_called()
        ensure.assert_not_called()


class VoiceTokenTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.session = General.create_session(consumer=self.consumer)

    def test_requires_jwt(self):
        response = self._post(VOICE_TOKEN_PATH, {})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @mock.patch("api.voice.services.mint_conversation_credentials")
    def test_mints_grant_and_returns_extra_body(self, mint):
        mint.return_value = {
            "signed_url": "wss://example.elevenlabs.io/signed",
            "conversation_token": "el_conversation_token",
        }

        response = self._post(VOICE_TOKEN_PATH, {}, access_token=self.access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)

        extra = response.json["custom_llm_extra_body"]
        grant_value = extra["grant"]
        self.assertTrue(grant_value)
        self.assertNotEqual(grant_value, self.consumer.user_id)
        self.assertEqual(response.json["conversation_token"], "el_conversation_token")
        self.assertEqual(response.json["signed_url"], "wss://example.elevenlabs.io/signed")
        self.assertEqual(response.json["session_id"], self.session.id)
        self.assertEqual(response.json["voice_id"], "female_irish")
        self.assertEqual(
            response.json["elevenlabs_voice_id"],
            VOICE_LIBRARY_IDS["female_irish"],
        )

        grant = VoiceGrant.objects.get(session=self.session, consumer=self.consumer)
        self.assertEqual(grant.token_hash, hash_grant_token(grant_value))
        self.assertNotEqual(grant.token_hash, grant_value)
        self.assertGreater(grant.expires_at, timezone.now())
        self.assertIsNone(grant.elevenlabs_conversation_id)
        self.assertIsNone(grant.revoked_at)

    @mock.patch("api.voice.services.mint_conversation_credentials")
    def test_rejects_exercise_session(self, mint):
        mint.return_value = {
            "signed_url": "wss://example.elevenlabs.io/signed",
            "conversation_token": "el_conversation_token",
        }
        exercise = General.create_exercise()
        self.session.exercise = exercise
        self.session.save(update_fields=["exercise"])

        response = self._post(
            VOICE_TOKEN_PATH,
            {"session_id": self.session.id},
            access_token=self.access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(VoiceGrant.objects.filter(session=self.session).count(), 0)

    @mock.patch("api.voice.services.mint_conversation_credentials")
    def test_returns_saved_voice_mapping(self, mint):
        mint.return_value = {
            "signed_url": "wss://example.elevenlabs.io/signed",
            "conversation_token": "el_conversation_token",
        }
        prefs = UserSettings.for_user(self.consumer.user)
        prefs.voice_id = UserSettings.VoiceId.MALE_IRISH
        prefs.save(update_fields=["voice_id"])

        response = self._post(VOICE_TOKEN_PATH, {}, access_token=self.access_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["voice_id"], "male_irish")
        self.assertEqual(
            response.json["elevenlabs_voice_id"],
            VOICE_LIBRARY_IDS["male_irish"],
        )


@override_settings(
    ELEVENLABS_API_KEY="sk_test",
    ELEVENLABS_API_BASE="https://api.elevenlabs.io",
)
class VoiceTtsTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.other = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.session = General.create_session(consumer=self.consumer)
        self.agent_participant = Participant.objects.filter(
            session=self.session, consumer__isnull=True, agent=self.consumer.agent
        ).first()
        self.user_participant = Participant.objects.filter(
            session=self.session, consumer=self.consumer, agent__isnull=True
        ).first()
        self.agent_message = Message.objects.create(
            session=self.session,
            sender=self.agent_participant,
            text="Take a slow breath with me.",
        )
        self.user_message = Message.objects.create(
            session=self.session,
            sender=self.user_participant,
            text="I am feeling anxious.",
        )

    def _post_tts(self, data, access_token=None):
        return self.client.post(
            VOICE_TTS_PATH,
            data=json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=access_token if access_token is not None else self.access_token,
        )

    def test_requires_jwt(self):
        response = self._post_tts({"message_id": self.agent_message.id}, access_token="")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_requires_message_id(self):
        response = self._post_tts({})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["message_id"], "This field is required.")

    def test_rejects_unknown_message(self):
        response = self._post_tts({"message_id": "msg_does_not_exist"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["message_id"], "Message not found.")

    def test_rejects_other_consumers_message(self):
        other_session = General.create_session(consumer=self.other)
        other_agent = Participant.objects.filter(
            session=other_session, consumer__isnull=True, agent=self.other.agent
        ).first()
        other_message = Message.objects.create(
            session=other_session,
            sender=other_agent,
            text="This belongs to someone else.",
        )
        response = self._post_tts({"message_id": other_message.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["message_id"], "Message not found.")

    def test_rejects_user_message(self):
        response = self._post_tts({"message_id": self.user_message.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Only Toni's messages can be read aloud.")

    def test_rejects_empty_agent_text(self):
        empty = Message.objects.create(
            session=self.session,
            sender=self.agent_participant,
            text="   ",
        )
        response = self._post_tts({"message_id": empty.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "This message has no speakable text.")

    @override_settings(ELEVENLABS_API_KEY="")
    def test_unconfigured_key_returns_503(self):
        response = self._post_tts({"message_id": self.agent_message.id})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("ELEVENLABS_API_KEY", response.json()["detail"])

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_returns_mpeg_and_does_not_need_agent_id(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3fake-mp3",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )

        with override_settings(ELEVENLABS_AGENT_ID=""):
            response = self._post_tts({"message_id": self.agent_message.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("audio/mpeg"))
        self.assertEqual(response.content, b"ID3fake-mp3")
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_LIBRARY_IDS['female_irish']}",
        )
        self.assertEqual(kwargs["params"]["output_format"], "mp3_44100_128")
        self.assertEqual(kwargs["headers"]["xi-api-key"], "sk_test")
        self.assertEqual(
            kwargs["json"],
            {"text": "Take a slow breath with me.", "model_id": DEFAULT_TTS_MODEL_ID},
        )

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_uses_saved_voice_mapping(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3fake-mp3",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )
        prefs = UserSettings.for_user(self.consumer.user)
        prefs.voice_id = UserSettings.VoiceId.MALE_IRISH
        prefs.save(update_fields=["voice_id"])

        response = self._post_tts({"message_id": self.agent_message.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        args, _kwargs = post.call_args
        self.assertEqual(
            args[0],
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_LIBRARY_IDS['male_irish']}",
        )

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_allows_exercise_session_messages(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3fake-mp3",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )
        exercise = General.create_exercise()
        self.session.exercise = exercise
        self.session.save(update_fields=["exercise"])

        response = self._post_tts({"message_id": self.agent_message.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"ID3fake-mp3")

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_forwards_elevenlabs_failure(self, post):
        failed = mock.Mock(ok=False, status_code=401, text='{"detail":{"message":"invalid api key"}}')
        failed.json.return_value = {"detail": {"message": "invalid api key"}}
        post.return_value = failed

        response = self._post_tts({"message_id": self.agent_message.id})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("invalid api key", response.json()["detail"])


@override_settings(
    ELEVENLABS_API_KEY="sk_test",
    ELEVENLABS_API_BASE="https://api.elevenlabs.io",
)
class VoicePreviewTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)

    def _post_preview(self, data, access_token=None):
        return self.client.post(
            VOICE_PREVIEW_PATH,
            data=json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=access_token if access_token is not None else self.access_token,
        )

    def test_requires_jwt(self):
        response = self._post_preview({}, access_token="")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_unknown_voice_id(self):
        response = self._post_preview({"voice_id": "female_american"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("voice_id", response.json())

    @override_settings(ELEVENLABS_API_KEY="")
    def test_unconfigured_key_returns_503(self):
        response = self._post_preview({"voice_id": "male_irish"})
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("ELEVENLABS_API_KEY", response.json()["detail"])

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_uses_saved_voice_when_omitted(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3preview",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )
        prefs = UserSettings.for_user(self.consumer.user)
        prefs.voice_id = UserSettings.VoiceId.MALE_IRISH
        prefs.save(update_fields=["voice_id"])

        response = self._post_preview({})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response["Content-Type"].startswith("audio/mpeg"))
        self.assertEqual(response.content, b"ID3preview")
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_LIBRARY_IDS['male_irish']}",
        )
        self.assertEqual(kwargs["json"]["text"], VOICE_PREVIEW_TEXT)
        stored = UserSettings.objects.get(user=self.consumer.user)
        self.assertEqual(stored.voice_id, "male_irish")

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_previews_requested_voice_without_saving(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3preview",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )

        response = self._post_preview({"voice_id": "male_irish"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_LIBRARY_IDS['male_irish']}",
        )
        self.assertEqual(kwargs["json"]["text"], VOICE_PREVIEW_TEXT)
        stored = UserSettings.objects.get(user=self.consumer.user)
        self.assertEqual(stored.voice_id, "female_irish")

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_previews_new_voices_without_saving(self, post):
        post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            content=b"ID3preview",
            headers={"Content-Type": "audio/mpeg"},
            text="",
        )
        for voice_id in (
            "american_male",
            "american_female",
            "british_female",
            "british_male",
        ):
            post.reset_mock()
            response = self._post_preview({"voice_id": voice_id})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            args, _kwargs = post.call_args
            self.assertEqual(
                args[0],
                f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_LIBRARY_IDS[voice_id]}",
            )
            stored = UserSettings.objects.get(user=self.consumer.user)
            self.assertEqual(stored.voice_id, "female_irish")

    @mock.patch("api.voice.elevenlabs_client.requests.post")
    def test_forwards_elevenlabs_failure(self, post):
        failed = mock.Mock(ok=False, status_code=401, text='{"detail":{"message":"invalid api key"}}')
        failed.json.return_value = {"detail": {"message": "invalid api key"}}
        post.return_value = failed

        response = self._post_preview({"voice_id": "female_irish"})
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("invalid api key", response.json()["detail"])


@override_settings(ELEVENLABS_LLM_SECRET=LLM_SECRET, ELEVENLABS_LLM_FILLER="Let me think about that... ")
class CustomLlmTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.other = Auth.create_consumer()
        self.session = General.create_session(consumer=self.consumer)
        self.grant, self.raw_token = VoiceGrant.issue(
            consumer=self.consumer,
            session=self.session,
        )
        self.client = APIClient()

    def _post_completions(self, payload, bearer=LLM_SECRET):
        headers = {}
        if bearer is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {bearer}"
        return self.client.post(
            CHAT_COMPLETIONS_PATH,
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

    def _payload(self, user_text="Hello Toni", extra=None, messages=None, **extra_fields):
        body = {
            "messages": messages
            if messages is not None
            else [
                {"role": "system", "content": "ignore this history"},
                {"role": "assistant", "content": "previous assistant turn"},
                {"role": "user", "content": "first user turn"},
                {"role": "user", "content": user_text},
            ],
            "model": "gpt-4o",
            "stream": True,
            "elevenlabs_extra_body": extra
            if extra is not None
            else {"grant": self.raw_token},
        }
        body.update(extra_fields)
        return body

    def test_forbidden_without_secret(self):
        response = self._post_completions(self._payload(), bearer=None)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_forbidden_with_wrong_secret(self):
        response = self._post_completions(self._payload(), bearer="wrong-secret")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_grant(self):
        response = self._post_completions(
            self._payload(extra={"grant": "not-a-real-grant"})
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ignores_body_user_ids(self):
        mocked = GeneralResponse(
            text="Voice reply from Toni",
            reasoning="should not be spoken",
            suggested_responses=["Nope"],
        )
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(
                self._payload(
                    extra={
                        "grant": self.raw_token,
                        "user_id": self.other.user_id,
                        "consumer_id": self.other.user_id,
                    },
                    user_id=self.other.user_id,
                    consumer_id=self.other.user_id,
                    user=self.other.user_id,
                )
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(
                response["Content-Type"].startswith("text/event-stream"),
                response["Content-Type"],
            )
            body = _sse_body(response)

        contents = _sse_contents(body)
        self.assertTrue(body.strip().endswith("data: [DONE]"))
        self.assertEqual(contents[0].strip(), "Let me think about that...")
        self.assertIn("Voice reply from Toni", contents)
        self.assertNotIn("Nope", body)
        self.assertNotIn("should not be spoken", body)

        user_messages = Message.objects.filter(
            session=self.session,
            sender__consumer=self.consumer,
        )
        self.assertEqual(user_messages.count(), 1)
        self.assertEqual(user_messages.get().text, "Hello Toni")
        self.assertEqual(
            Message.objects.filter(session=self.session, sender__consumer=self.other).count(),
            0,
        )
        agent_message = Message.objects.filter(
            session=self.session,
            sender__agent=self.consumer.agent,
        ).get()
        self.assertEqual(agent_message.text, "Voice reply from Toni")

    @override_settings(ELEVENLABS_LLM_FILLER="")
    def test_empty_filler_still_keeps_the_sse_stream_alive(self):
        mocked = GeneralResponse(
            text="Voice reply from Toni",
            reasoning="should not be spoken",
            suggested_responses=[],
        )
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(self._payload())
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            body = _sse_body(response)

        contents = _sse_contents(body)
        self.assertEqual(contents[0], "Let me think about that... ")
        self.assertIn("Voice reply from Toni", contents)
        self.assertIn("flush_padding", body)

    def test_filler_and_flush_precede_gemini(self):
        mocked = GeneralResponse(
            text="Voice reply from Toni",
            reasoning="r",
            suggested_responses=[],
        )
        called = []

        def track(*args, **kwargs):
            called.append(1)
            return mocked, {}, None, None

        with mock.patch("api.utils.Agent.get_response", side_effect=track):
            response = self._post_completions(self._payload())
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            iterator = iter(response.streaming_content)

            first = next(iterator)
            self.assertIn(b"Let me think about that... ", first)
            self.assertEqual(called, [])

            second = next(iterator)
            self.assertGreater(len(second), 8000)
            self.assertIn(b"flush_padding", second)
            self.assertEqual(called, [])

            rest = b"".join(iterator)

        self.assertEqual(called, [1])
        self.assertIn(b"Voice reply from Toni", rest)

    def test_conversation_id_mismatch_is_rejected(self):
        mocked = GeneralResponse(text="ok", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            first = self._post_completions(
                self._payload(
                    extra={"grant": self.raw_token, "conversation_id": "conv_one"}
                )
            )
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            _sse_body(first)

        self.grant.refresh_from_db()
        self.assertEqual(self.grant.elevenlabs_conversation_id, "conv_one")

        second = self._post_completions(
            self._payload(
                extra={"grant": self.raw_token, "conversation_id": "conv_two"}
            )
        )
        self.assertEqual(second.status_code, status.HTTP_403_FORBIDDEN)

    def test_uses_latest_user_message_only(self):
        mocked = GeneralResponse(text="Heard you", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(
                self._payload(
                    messages=[
                        {"role": "user", "content": "old turn"},
                        {"role": "assistant", "content": "old reply"},
                        {"role": "user", "content": "latest spoken turn"},
                    ]
                )
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            _sse_body(response)
            user_message = get_agent_response.call_args.kwargs["consumer_message"]

        self.assertEqual(user_message.text, "latest spoken turn")
        self.assertEqual(
            Message.objects.filter(session=self.session, sender__consumer=self.consumer)
            .get()
            .text,
            "latest spoken turn",
        )

    def test_dict_user_content_is_parsed(self):
        mocked = GeneralResponse(text="Heard you", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(
                self._payload(
                    messages=[
                        {"role": "user", "content": {"type": "text", "text": "dict spoken turn"}},
                    ]
                )
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            _sse_body(response)
            user_message = get_agent_response.call_args.kwargs["consumer_message"]

        self.assertEqual(user_message.text, "dict spoken turn")

    def test_empty_last_user_turn_does_not_replay_previous(self):
        mocked = GeneralResponse(text="should not speak", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(
                self._payload(
                    messages=[
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi there"},
                        {"role": "user", "content": ""},
                    ]
                )
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            body = _sse_body(response)
            get_agent_response.assert_not_called()

        self.assertTrue(body.strip().endswith("data: [DONE]"))
        self.assertNotIn("should not speak", body)
        self.assertEqual(
            Message.objects.filter(session=self.session, sender__consumer=self.consumer).count(),
            0,
        )

    def test_repeat_utterance_does_not_call_gemini(self):
        mocked = GeneralResponse(text="Heard you", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            first = self._post_completions(self._payload(user_text="hello again"))
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            _sse_body(first)
            self.assertEqual(get_agent_response.call_count, 1)

            second = self._post_completions(self._payload(user_text="hello again"))
            self.assertEqual(second.status_code, status.HTTP_200_OK)
            second_body = _sse_body(second)
            self.assertEqual(get_agent_response.call_count, 1)
            self.assertIn("Heard you", _sse_contents(second_body))

        self.assertEqual(
            Message.objects.filter(session=self.session, sender__consumer=self.consumer).count(),
            1,
        )

    def test_spoken_yes_skips_gemini_and_clears_offer(self):
        from ...participant.models import Participant
        from ...utils import Constants

        exercise = General.create_exercise()
        exercise.status = Constants.EXERCISE_STATUS_PUBLISHED
        exercise.save(update_fields=["status"])
        agent_participant = Participant.objects.filter(
            session=self.session,
            agent=self.consumer.agent,
        ).first()
        offer = Message.objects.create(
            session=self.session,
            sender=agent_participant,
            text=f"Would you like to start {exercise.title}?",
            exercise=exercise,
            suggested_responses=list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES),
            reasoning="triage",
        )

        mocked = GeneralResponse(text="should not speak", reasoning="r", suggested_responses=[])
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_completions(self._payload(user_text="yeah"))
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            body = _sse_body(response)
            get_agent_response.assert_not_called()

        self.assertNotIn("should not speak", body)
        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])
        user_messages = Message.objects.filter(
            session=self.session,
            sender__consumer=self.consumer,
        )
        self.assertEqual(user_messages.count(), 1)
        self.assertEqual(user_messages.get().text, "Yes")
        self.session.refresh_from_db()
        self.assertIsNone(self.session.exercise_id)


@override_settings(ELEVENLABS_WEBHOOK_SECRET=WEBHOOK_SECRET)
class VoiceWebhookTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.session = General.create_session(consumer=self.consumer)
        self.grant, self.raw_token = VoiceGrant.issue(
            consumer=self.consumer,
            session=self.session,
        )
        self.grant.elevenlabs_conversation_id = "conv_live"
        self.grant.save(update_fields=["elevenlabs_conversation_id"])

    def _post_webhook(self, payload, signature=None, secret=WEBHOOK_SECRET):
        raw = json.dumps(payload).encode("utf-8")
        headers = {}
        if signature is not False:
            headers["HTTP_ELEVENLABS_SIGNATURE"] = signature or _sign_webhook(raw, secret)
        return self.client.post(
            WEBHOOK_PATH,
            data=raw,
            content_type="application/json",
            **headers,
        )

    def test_bad_hmac_is_unauthorized(self):
        response = self._post_webhook(
            {"type": "post_call_transcription", "data": {"conversation_id": "conv_live"}},
            signature="t=1,v0=deadbeef",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_signature_is_unauthorized(self):
        response = self._post_webhook(
            {"type": "post_call_transcription", "data": {"conversation_id": "conv_live"}},
            signature=False,
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reconcile_is_idempotent_with_live_path(self):
        from ...participant.models import Participant

        consumer_participant = Participant.objects.filter(
            session=self.session, consumer=self.consumer
        ).first()
        agent_participant = Participant.objects.filter(
            session=self.session, agent=self.consumer.agent
        ).first()
        Message.objects.create(
            session=self.session,
            sender=consumer_participant,
            text="Hello from voice",
            voice_conversation_id="conv_live",
            voice_turn_index=0,
        )
        Message.objects.create(
            session=self.session,
            sender=agent_participant,
            text="Toni already replied",
            voice_conversation_id="conv_live",
            voice_turn_index=1,
        )

        payload = {
            "type": "post_call_transcription",
            "data": {
                "conversation_id": "conv_live",
                "transcript": [
                    {"role": "user", "message": "Hello from voice"},
                    {"role": "agent", "message": "Toni already replied"},
                    {"role": "user", "message": "missed live turn"},
                ],
            },
        }
        response = self._post_webhook(payload)
        body = response.json()
        self.assertEqual(response.status_code, status.HTTP_200_OK, body)
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["stamped"], 0)

        second = self._post_webhook(payload)
        second_body = second.json()
        self.assertEqual(second.status_code, status.HTTP_200_OK, second_body)
        self.assertEqual(second_body["created"], 0)
        self.assertEqual(
            Message.objects.filter(session=self.session, voice_conversation_id="conv_live").count(),
            3,
        )
        self.assertEqual(
            Message.objects.filter(session=self.session, text="Hello from voice").count(),
            1,
        )
