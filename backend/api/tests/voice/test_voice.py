import hashlib
import hmac
import json
import time
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from ...message.models import Message
from ...tests.TestCase import TestCase
from ...utils.Agent import GeneralResponse
from ...voice.models import VoiceGrant, hash_grant_token
from ..utils.manager import Auth, General

LLM_SECRET = "test-elevenlabs-llm-secret"
WEBHOOK_SECRET = "test-elevenlabs-webhook-secret"
VOICE_TOKEN_PATH = "/voice/token"
CHAT_COMPLETIONS_PATH = "/internal/elevenlabs/v1/chat/completions"
WEBHOOK_PATH = "/internal/elevenlabs/webhook"


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
