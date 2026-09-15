from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ..TestCase import TestCase
from ..utils.manager import Auth
from ...knowledge.followup import (
    FollowupReply,
    format_onboarding_followup_block,
    greeting_user_prompt_for_session,
    handle_onboarding_followup_reply,
    is_answer_vague,
    is_onboarding_followup_session,
    maybe_start_onboarding_followup,
    should_classify_onboarding_answer,
)
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...knowledge.services import write_knowledge_entry
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...utils import Constants
from ...utils.Agent import GeneralResponse


class VaguenessClassifierTests(TestCase):
    def test_should_classify_only_initial_text(self):
        self.assertTrue(
            should_classify_onboarding_answer(
                variant=Constants.KNOWLEDGE_FLOW_INITIAL,
                response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
                classify=True,
            )
        )
        self.assertFalse(
            should_classify_onboarding_answer(
                variant=Constants.KNOWLEDGE_FLOW_RETURN,
                response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
                classify=True,
            )
        )
        self.assertFalse(
            should_classify_onboarding_answer(
                variant=Constants.KNOWLEDGE_FLOW_INITIAL,
                response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
                classify=True,
            )
        )
        self.assertFalse(
            should_classify_onboarding_answer(
                variant=Constants.KNOWLEDGE_FLOW_INITIAL,
                response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
                classify=False,
            )
        )

    def test_is_answer_vague_uses_gemini_result(self):
        with mock.patch(
            "api.utils.AI.AI.ask",
            return_value={"is_vague": True, "reasoning": "generic"},
        ):
            self.assertTrue(is_answer_vague("How is sleep?", "fine"))
        with mock.patch(
            "api.utils.AI.AI.ask",
            return_value={"is_vague": False, "reasoning": "ok"},
        ):
            self.assertFalse(is_answer_vague("How is sleep?", "I wake at 3am most nights"))

    def test_is_answer_vague_fails_open(self):
        with mock.patch("api.utils.AI.AI.ask", side_effect=RuntimeError("down")):
            self.assertFalse(is_answer_vague("How is sleep?", "fine"))
        self.assertFalse(is_answer_vague("How is sleep?", "   "))


class OnboardingVaguenessTests(TestCase):
    def setUp(self):
        super().setUp()
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.worry = KnowledgeField.objects.create(
            key="main_worry",
            label="Main worry",
            category="Wellbeing",
            active=True,
        )
        self.q_worry = KnowledgeQuestion.objects.create(
            prompt="What is worrying you most right now?",
            target_field=self.worry,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            flows=[Constants.KNOWLEDGE_FLOW_INITIAL],
            order=1,
            active=True,
        )

    def test_flags_vague_free_text(self):
        with mock.patch(
            "api.knowledge.followup.is_answer_vague", return_value=True
        ) as classify:
            response = self._post(
                "/onboarding/answers",
                {
                    "variant": "initial",
                    "complete": True,
                    "answers": [
                        {
                            "knowledge_question_id": self.q_worry.id,
                            "value": "stuff",
                        }
                    ],
                },
                self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        classify.assert_called_once()
        entry = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertTrue(entry.needs_followup)
        self.assertEqual(entry.followup_prompt, "What is worrying you most right now?")
        self.assertEqual(response.json["entries"][0]["needs_followup"], True)

    def test_placeholder_complete_does_not_classify(self):
        with mock.patch("api.knowledge.followup.is_answer_vague") as skipped:
            complete = self._post("/onboarding/complete", {}, self.token)
        self.assertEqual(complete.status_code, status.HTTP_200_OK, complete.json)
        skipped.assert_not_called()
        placeholder = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertFalse(placeholder.needs_followup)


@override_settings(AI_ASYNC_MESSAGES=False)
class FirstChatFollowupTests(TestCase):
    def setUp(self):
        super().setUp()
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.consumer.onboarded = True
        self.consumer.save(update_fields=["onboarded"])
        self.field = KnowledgeField.objects.create(
            key="main_worry",
            label="Main worry",
            active=True,
        )
        self.question = KnowledgeQuestion.objects.create(
            prompt="What is worrying you most?",
            target_field=self.field,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_TEXT,
            active=True,
        )
        self.entry = write_knowledge_entry(
            consumer=self.consumer,
            field=self.field,
            value="stuff",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
            knowledge_question=self.question,
            needs_followup=True,
            followup_prompt="What is worrying you most?",
        )

    def _session_with_latch(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        self.consumer.onboarding_followup_consumed_at = timezone.now()
        self.consumer.save(update_fields=["onboarding_followup_consumed_at"])
        session.refresh_from_db()
        self.consumer.refresh_from_db()
        session.consumer = self.consumer
        return session

    def test_today_greets_when_pending_followup(self):
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = (
                GeneralResponse(
                    text="Earlier you mentioned stuff was worrying you — what's that about?",
                    reasoning="followup",
                    suggested_responses=[],
                ),
                {},
                None,
                None,
            )
            response = self._get("/sessions/today", access_token=self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertIsNotNone(response.json["last_message"])
        self.assertIn("worrying", response.json["last_message"]["text"])
        self.consumer.refresh_from_db()
        self.assertIsNotNone(self.consumer.onboarding_followup_consumed_at)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 1)
        get_agent_response.assert_called_once()
        block = format_onboarding_followup_block(Session.objects.get(id=response.json["id"]))
        self.assertIn("ONBOARDING_FOLLOW_UP", block)
        self.assertIn("What is worrying you most?", block)

    def test_second_general_session_does_not_greet_again(self):
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = (
                GeneralResponse(text="Opener", reasoning="x", suggested_responses=[]),
                {},
                None,
                None,
            )
            first = self._get("/sessions/today", access_token=self.token)
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            second = self._post("/sessions", {}, access_token=self.token)

        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.json)
        self.assertIsNone(second.json["last_message"])
        self.assertEqual(get_agent_response.call_count, 1)

    def test_not_onboarded_does_not_consume_latch(self):
        self.consumer.onboarded = False
        self.consumer.save(update_fields=["onboarded"])
        session = Session.objects.create(consumer=self.consumer)
        maybe_start_onboarding_followup(session)
        self.consumer.refresh_from_db()
        self.assertIsNone(self.consumer.onboarding_followup_consumed_at)

    def test_specific_reply_writes_new_entry(self):
        session = self._session_with_latch()
        self.assertTrue(is_onboarding_followup_session(session))
        greeting_user_prompt_for_session(session)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 1)

        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        user_message = Message.objects.create(
            session=session,
            sender=participant,
            text="I lie awake replaying a fight I had with my sister",
        )
        with mock.patch("api.knowledge.followup.is_answer_vague", return_value=False):
            result = handle_onboarding_followup_reply(session, user_message)

        self.assertIsNone(result.canned_text)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.needs_followup)
        current = KnowledgeEntry.current_for(self.consumer, self.field)
        self.assertEqual(current.value, user_message.text)
        self.assertEqual(current.source, Constants.KNOWLEDGE_ENTRY_SOURCE_AI)
        self.assertFalse(current.needs_followup)
        self.assertNotEqual(current.id, self.entry.id)

    def test_vague_then_give_up(self):
        session = self._session_with_latch()
        greeting_user_prompt_for_session(session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()

        first = Message.objects.create(session=session, sender=participant, text="idk")
        with mock.patch("api.knowledge.followup.is_answer_vague", return_value=True):
            result = handle_onboarding_followup_reply(session, first)
        self.assertEqual(result.canned_text, Constants.KNOWLEDGE_FOLLOWUP_DIRECT_REASK)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 2)
        self.assertTrue(self.entry.needs_followup)

        second = Message.objects.create(
            session=session, sender=participant, text="whatever"
        )
        with mock.patch("api.knowledge.followup.is_answer_vague", return_value=True):
            result = handle_onboarding_followup_reply(session, second)
        self.assertIsNone(result.canned_text)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.needs_followup)
        current = KnowledgeEntry.current_for(self.consumer, self.field)
        self.assertEqual(current.id, self.entry.id)
        self.assertEqual(current.value, "stuff")

    def test_unsaved_greeting_message_is_not_classified(self):
        session = self._session_with_latch()
        greeting_user_prompt_for_session(session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        unsaved = Message(
            session=session, sender=participant, text="Please open this chat."
        )
        with mock.patch("api.knowledge.followup.is_answer_vague") as classify:
            result = handle_onboarding_followup_reply(session, unsaved)
        classify.assert_not_called()
        self.assertEqual(result, FollowupReply())
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.needs_followup)

    def test_message_api_sends_direct_reask(self):
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = (
                GeneralResponse(text="Opener", reasoning="x", suggested_responses=[]),
                {},
                None,
                None,
            )
            today = self._get("/sessions/today", access_token=self.token)
        session_id = today.json["id"]
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 1)

        with mock.patch("api.knowledge.followup.is_answer_vague", return_value=True):
            response = self._post(
                "/messages",
                {"text": "fine", "session": session_id},
                access_token=self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.assertEqual(response.json["text"], Constants.KNOWLEDGE_FOLLOWUP_DIRECT_REASK)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 2)
