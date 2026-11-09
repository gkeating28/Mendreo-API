"""High-risk close: own-risk phrases only, fixed reply, flag, and resume skip."""

import json
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from ...agent.models import Agent
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse, GeneralResponse
from ...utils.high_risk_copy import DEFAULT_HIGH_RISK_COPY, high_risk_chat_message
from ...utils.Mail import send_trust_and_safety_alert
from ...utils.risk import normalize_risk_level, risk_prescreen
from ...voice.models import VoiceGrant
from ..TestCase import TestCase
from ..utils.manager import Auth, General

LLM_SECRET = "test-elevenlabs-llm-secret"
CHAT_COMPLETIONS_PATH = "/internal/elevenlabs/v1/chat/completions"

FALSE_ALARMS = (
    "my friend died by suicide",
    "I read about suicide",
    "my friend killed himself",
    "I don't want to die",
    "I want to diet",
    "end my lifestyle",
    "I hurt myself playing football",
    "I used to self-harm",
)

MUST_CLOSE = (
    "I'm going to kill myself",
    "I've been thinking about ending my life",
    "I want to die",
)


def _sse_contents(response) -> list[str]:
    if getattr(response, "streaming", False):
        body = b"".join(response.streaming_content).decode("utf-8")
    else:
        body = response.content.decode("utf-8")
    texts = []
    for line in body.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[len("data: "):])
        content = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
        if content and content.strip():
            texts.append(content)
    return texts


class RiskPrescreenTests(TestCase):
    def test_own_risk_description_is_on_both_schemas(self):
        general = GeneralResponse.model_fields["risk_level"].description
        exercise = ExerciseStateResponse.model_fields["risk_level"].description
        self.assertEqual(general, exercise)
        self.assertIn("own risk", general)
        self.assertIn("something they read", general)

    def test_critical_maps_to_high(self):
        self.assertEqual(
            normalize_risk_level("critical"),
            Constants.LIVE_RISK_LEVEL_HIGH,
        )
        self.assertEqual(
            normalize_risk_level(" Critical "),
            Constants.LIVE_RISK_LEVEL_HIGH,
        )

    def test_phrases_use_word_boundaries_case_and_spacing(self):
        self.assertEqual(risk_prescreen("I WANT TO DIE"), Constants.LIVE_RISK_LEVEL_HIGH)
        self.assertEqual(
            risk_prescreen("I  want   to   die"),
            Constants.LIVE_RISK_LEVEL_HIGH,
        )
        self.assertEqual(risk_prescreen("I want to diet"), Constants.LIVE_RISK_LEVEL_NONE)
        self.assertEqual(risk_prescreen("end my lifestyle"), Constants.LIVE_RISK_LEVEL_NONE)
        self.assertEqual(risk_prescreen("suicide"), Constants.LIVE_RISK_LEVEL_LOW)
        self.assertEqual(
            risk_prescreen("I don’t want to die"),
            Constants.LIVE_RISK_LEVEL_NONE,
        )
        self.assertEqual(
            risk_prescreen("I DON'T want to die"),
            Constants.LIVE_RISK_LEVEL_NONE,
        )
        self.assertEqual(
            risk_prescreen("I do not want to die"),
            Constants.LIVE_RISK_LEVEL_NONE,
        )
        self.assertEqual(
            risk_prescreen("I no longer want to die"),
            Constants.LIVE_RISK_LEVEL_NONE,
        )
        self.assertEqual(
            risk_prescreen("I didnt want to die"),
            Constants.LIVE_RISK_LEVEL_NONE,
        )
        self.assertEqual(
            risk_prescreen("I don't want to die but I want to die"),
            Constants.LIVE_RISK_LEVEL_HIGH,
        )

    def test_false_alarm_phrases_are_not_high(self):
        for text in FALSE_ALARMS:
            with self.subTest(text=text):
                self.assertNotEqual(risk_prescreen(text), Constants.LIVE_RISK_LEVEL_HIGH)
                self.assertNotEqual(
                    risk_prescreen(text),
                    Constants.LIVE_RISK_LEVEL_MODERATE,
                )


class HighRiskTurnTests(TestCase):
    def _turn(self, text, model_level="none", model_text="Tell me a bit more.", exercise=None):
        consumer = Auth.create_consumer()
        session = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            completed=False if exercise else None,
            current_step_no=1 if exercise else None,
            total_steps_no=1 if exercise else None,
            state=(
                Constants.SESSION_STATE_STEP_ACTIVE
                if exercise
                else Constants.SESSION_STATE_GENERAL
            ),
        )
        user_sender, _agent_sender = Participant.create_participants(session)
        user_message = Message.objects.create(
            session=session,
            sender=user_sender,
            text=text,
        )
        mocked = GeneralResponse(
            text=model_text,
            reasoning="test",
            suggested_responses=["Tell me more"],
            risk_level=model_level,
        )
        with (
            patch("api.utils.session_close.close_session") as close,
            patch("api.tasks.notify_trust_and_safety.delay_on_commit") as queued,
            patch(
                "api.utils.Agent.get_response",
                return_value=(mocked, {}, None, None),
            ),
        ):
            agent_message = Agent.get_response(session=session, user_message=user_message)
        session.refresh_from_db()
        consumer.refresh_from_db()
        return consumer, session, agent_message, close, queued

    def _assert_closed(self, consumer, session, agent_message, close, queued, model_text):
        self.assertEqual(agent_message.text, high_risk_chat_message())
        self.assertNotEqual(agent_message.text, model_text)
        self.assertEqual(agent_message.suggested_responses, [])
        self.assertIsNotNone(agent_message.resources)
        self.assertIn("links", agent_message.resources)
        self.assertEqual(session.close_reason, Constants.CLOSE_REASON_HIGH_RISK)
        self.assertIsNotNone(session.closed_at)
        self.assertIsNone(session.rating)
        self.assertTrue(consumer.crisis_notice_pending)
        close.assert_not_called()
        queued.assert_called_once_with(session.id)

    def test_first_person_phrases_close_and_replace_the_reply(self):
        model_text = "That sounds very heavy."
        for text in MUST_CLOSE:
            with self.subTest(text=text):
                consumer, session, agent_message, close, queued = self._turn(
                    text,
                    model_level="low",
                    model_text=model_text,
                )
                self._assert_closed(
                    consumer, session, agent_message, close, queued, model_text
                )

    def test_model_high_without_keywords_closes(self):
        model_text = "I am here with you."
        consumer, session, agent_message, close, queued = self._turn(
            "I slept badly last night",
            model_level="high",
            model_text=model_text,
        )
        self.assertEqual(risk_prescreen("I slept badly last night"), Constants.LIVE_RISK_LEVEL_NONE)
        self._assert_closed(consumer, session, agent_message, close, queued, model_text)

    def test_model_critical_closes_as_high(self):
        model_text = "I am here with you."
        consumer, session, agent_message, close, queued = self._turn(
            "I slept badly last night",
            model_level="critical",
            model_text=model_text,
        )
        self._assert_closed(consumer, session, agent_message, close, queued, model_text)
        self.assertEqual(session.live_risk_level, Constants.LIVE_RISK_LEVEL_HIGH)

    def test_moderate_keeps_the_reply_and_does_not_close(self):
        model_text = "That sounds painful."
        consumer, session, agent_message, close, queued = self._turn(
            "I might harm myself",
            model_level="none",
            model_text=model_text,
        )
        self.assertEqual(agent_message.text, model_text)
        self.assertIsNotNone(agent_message.resources)
        self.assertIsNone(session.closed_at)
        self.assertIsNone(session.close_reason)
        self.assertFalse(consumer.crisis_notice_pending)
        close.assert_not_called()
        queued.assert_not_called()

    def test_false_alarms_do_not_close_or_flag(self):
        model_text = "I'm glad you told me."
        for text in FALSE_ALARMS:
            with self.subTest(text=text):
                consumer, session, agent_message, close, queued = self._turn(
                    text,
                    model_level="none",
                    model_text=model_text,
                )
                self.assertEqual(agent_message.text, model_text)
                self.assertIsNone(agent_message.resources)
                self.assertIsNone(session.closed_at)
                self.assertFalse(consumer.crisis_notice_pending)
                close.assert_not_called()
                queued.assert_not_called()

    def test_exercise_high_turn_closes_without_the_rating_pass(self):
        exercise = General.create_exercise()
        model_text = "We can stay with that."
        consumer, session, agent_message, close, queued = self._turn(
            "I want to die",
            model_level="none",
            model_text=model_text,
            exercise=exercise,
        )
        self._assert_closed(consumer, session, agent_message, close, queued, model_text)
        self.assertEqual(session.current_step_no, 1)
        self.assertFalse(session.completed)

    def test_blank_trust_and_safety_email_sends_nothing(self):
        address = Setting.get_or_create_trust_and_safety_email()
        address.value = ""
        address.save()
        _consumer, session, _message, _close, queued = self._turn("I want to die", "high")
        queued.assert_called_once_with(session.id)
        with patch("resend.Emails.send") as send:
            send_trust_and_safety_alert(session.id)
        send.assert_not_called()


class HighRiskEndpointTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_consumer_access_token(self.consumer)
        self.other = Auth.create_consumer()
        self.other_token = Auth.get_consumer_access_token(self.other)

    def _close_general(self):
        session = Session.objects.create(consumer=self.consumer, exercise=None)
        user_sender, _agent_sender = Participant.create_participants(session)
        user_message = Message.objects.create(
            session=session,
            sender=user_sender,
            text="I want to die",
        )
        mocked = GeneralResponse(
            text="model text that must not be saved",
            reasoning="test",
            suggested_responses=["More"],
            risk_level="none",
        )
        with (
            patch("api.utils.session_close.close_session"),
            patch("api.tasks.notify_trust_and_safety.delay_on_commit"),
            patch(
                "api.utils.Agent.get_response",
                return_value=(mocked, {}, None, None),
            ),
        ):
            Agent.get_response(session=session, user_message=user_message)
        session.refresh_from_db()
        self.consumer.refresh_from_db()
        return session

    def test_post_messages_is_refused_after_a_high_close(self):
        session = self._close_general()
        before = Message.objects.filter(session=session).count()
        response = self._post(
            "/messages",
            {"session": session.id, "text": "are you still there"},
            self.token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)
        self.assertEqual(response.json["code"], [Constants.HIGH_RISK_CLOSED_CODE])
        self.assertEqual(response.json["session"], ["This chat is closed."])
        self.assertEqual(Message.objects.filter(session=session).count(), before)

    def test_resume_skips_a_high_risk_close(self):
        with patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None):
            exercise = General.create_exercise()
            first = General.start_session(consumer=self.consumer, exercise=exercise)
            first.closed_at = first.created_at
            first.close_reason = Constants.CLOSE_REASON_HIGH_RISK
            first.save(update_fields=["closed_at", "close_reason", "updated_at"])

            started = self._get(
                "/sessions/start",
                query_params_dict={"exercise_id": exercise.id},
                access_token=self.token,
            )
            self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
            self.assertNotEqual(started.json["id"], first.id)

            listed = self._get(
                "/sessions",
                query_params_dict={"general": "false"},
                access_token=self.token,
            )
            rows = listed.json["results"] if isinstance(listed.json, dict) else listed.json
            self.assertNotIn(first.id, [row["id"] for row in rows])

        closed_chat = Session.objects.create(consumer=self.consumer, exercise=None)
        closed_chat.closed_at = closed_chat.created_at
        closed_chat.close_reason = Constants.CLOSE_REASON_HIGH_RISK
        closed_chat.save(update_fields=["closed_at", "close_reason", "updated_at"])

        today = self._get("/sessions/today", access_token=self.token)
        self.assertEqual(today.status_code, status.HTTP_200_OK, today.json)
        self.assertNotEqual(today.json["id"], closed_chat.id)
        resumed = Session.objects.get(id=today.json["id"])
        self.assertNotEqual(resumed.close_reason, Constants.CLOSE_REASON_HIGH_RISK)

        created = self._post("/sessions", {}, self.token)
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)
        self.assertNotEqual(created.json["id"], closed_chat.id)

    def test_consumer_payload_and_dismiss_are_owner_only(self):
        session = self._close_general()
        self.assertIsNotNone(session.closed_at)

        detail = self._get(f"/consumers/{self.consumer.user_id}", access_token=self.token)
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        self.assertIs(detail.json["crisis_notice_pending"], True)

        notice = self._get(
            f"/consumers/{self.consumer.user_id}/crisis-notice",
            access_token=self.token,
        )
        self.assertEqual(notice.status_code, status.HTTP_200_OK, notice.json)
        self.assertIs(notice.json["crisis_notice_pending"], True)
        self.assertEqual(notice.json["modal_title"], DEFAULT_HIGH_RISK_COPY["modal_title"])
        self.assertEqual(notice.json["modal_lines"][0]["label"], "Samaritans")
        self.assertNotIn("chat_message", notice.json)

        stolen = self._post(
            f"/consumers/{self.consumer.user_id}/crisis-notice/dismiss",
            {},
            self.other_token,
        )
        self.assertEqual(stolen.status_code, status.HTTP_404_NOT_FOUND)
        other_read = self._get(
            f"/consumers/{self.consumer.user_id}/crisis-notice",
            access_token=self.other_token,
        )
        self.assertEqual(other_read.status_code, status.HTTP_404_NOT_FOUND)
        self.consumer.refresh_from_db()
        self.assertTrue(self.consumer.crisis_notice_pending)

        admin = self._get(
            f"/consumers/{self.consumer.user_id}/crisis-notice",
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(admin.status_code, status.HTTP_403_FORBIDDEN)

        token = Auth.get_platform_admin_access_token()
        saved = self._post(
            "/settings",
            {
                "survey_enabled": True,
                "high_risk_copy": {"modal_title": "Please get help"},
            },
            token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.data)
        self.assertEqual(saved.data["high_risk_copy"]["modal_title"], "Please get help")
        edited = self._get(
            f"/consumers/{self.consumer.user_id}/crisis-notice",
            access_token=self.token,
        )
        self.assertEqual(edited.json["modal_title"], "Please get help")
        self.assertEqual(
            edited.json["modal_body"],
            DEFAULT_HIGH_RISK_COPY["modal_body"],
        )

        cleared = self._post(
            f"/consumers/{self.consumer.user_id}/crisis-notice/dismiss",
            {},
            self.token,
        )
        self.assertEqual(cleared.status_code, status.HTTP_200_OK, cleared.json)
        self.assertIs(cleared.json["crisis_notice_pending"], False)
        self.consumer.refresh_from_db()
        self.assertFalse(self.consumer.crisis_notice_pending)
        hidden = self._get(
            f"/consumers/{self.consumer.user_id}/crisis-notice",
            access_token=self.token,
        )
        self.assertIs(hidden.json["crisis_notice_pending"], False)
        self.assertNotIn("modal_title", hidden.json)
        detail = self._get(f"/consumers/{self.consumer.user_id}", access_token=self.token)
        self.assertIs(detail.json["crisis_notice_pending"], False)

    def test_blank_copy_field_uses_the_default(self):
        token = Auth.get_platform_admin_access_token()
        saved = self._post(
            "/settings",
            {
                "survey_enabled": True,
                "high_risk_copy": {"chat_message": ""},
            },
            token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, saved.data)
        self.assertEqual(
            saved.data["high_risk_copy"]["chat_message"],
            DEFAULT_HIGH_RISK_COPY["chat_message"],
        )
        listed = self._get("/settings", access_token=token)
        self.assertEqual(
            listed.json["high_risk_copy"]["chat_message"],
            DEFAULT_HIGH_RISK_COPY["chat_message"],
        )


@override_settings(ELEVENLABS_LLM_SECRET=LLM_SECRET)
class HighRiskVoiceTests(TestCase):
    def test_completion_speaks_the_fixed_message_and_stops(self):
        consumer = Auth.create_consumer()
        session = General.create_session(consumer=consumer)
        grant, raw_token = VoiceGrant.issue(consumer=consumer, session=session)
        mocked = GeneralResponse(
            text="model text that must not be spoken",
            reasoning="test",
            suggested_responses=["More"],
            risk_level="high",
        )
        client = APIClient()

        def post(user_text):
            return client.post(
                CHAT_COMPLETIONS_PATH,
                data=json.dumps(
                    {
                        "messages": [{"role": "user", "content": user_text}],
                        "model": "gpt-4o",
                        "stream": True,
                        "elevenlabs_extra_body": {"grant": raw_token},
                    }
                ),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {LLM_SECRET}",
            )

        with (
            patch("api.tasks.notify_trust_and_safety.delay_on_commit"),
            patch("api.utils.session_close.close_session") as close,
            patch("api.utils.Agent.get_response", return_value=(mocked, {}, None, None)) as model,
        ):
            first = post("I want to die")
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            spoken = " ".join(_sse_contents(first))
            self.assertIn(high_risk_chat_message(), spoken)
            self.assertNotIn("model text that must not be spoken", spoken)
            self.assertEqual(model.call_count, 1)
            close.assert_not_called()

            second = post("hello again")
            self.assertEqual(second.status_code, status.HTTP_200_OK)
            self.assertEqual(model.call_count, 1)
            self.assertNotIn(high_risk_chat_message(), " ".join(_sse_contents(second)))

        session.refresh_from_db()
        consumer.refresh_from_db()
        self.assertEqual(session.close_reason, Constants.CLOSE_REASON_HIGH_RISK)
        self.assertTrue(consumer.crisis_notice_pending)
        saved = Message.objects.filter(session=session, sender__agent=consumer.agent).get()
        self.assertEqual(saved.text, high_risk_chat_message())
        self.assertIsNotNone(saved.resources)
        self.assertEqual(grant.session_id, session.id)
