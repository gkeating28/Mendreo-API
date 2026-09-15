from unittest import mock

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ..TestCase import TestCase
from ..utils.manager import Auth
from ...knowledge.followup import (
    FollowupReply,
    activate_next_followup,
    flag_onboarding_answer_for_followup,
    format_onboarding_followup_block,
    handle_onboarding_followup_reply,
    is_answer_vague,
    is_onboarding_followup_session,
    looks_thin_opener,
    looks_vague,
    maybe_start_onboarding_followup,
    should_classify_onboarding_answer,
    should_inject_onboarding_followup,
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

    def test_looks_vague_matches_platitudes_only(self):
        self.assertTrue(looks_vague("stuff"))
        self.assertTrue(looks_vague("  Fine. "))
        self.assertTrue(looks_vague("I'm okay"))
        self.assertTrue(looks_vague("idk"))
        self.assertFalse(looks_vague("Full-time"))
        self.assertFalse(looks_vague("I work 3 days and freelance the rest"))
        self.assertFalse(looks_vague(""))

    def test_looks_thin_opener_greetings(self):
        self.assertTrue(looks_thin_opener("Hello"))
        self.assertTrue(looks_thin_opener("hey Toni"))
        self.assertTrue(looks_thin_opener("idk"))
        self.assertFalse(looks_thin_opener("I lie awake replaying a fight with my sister"))
        self.assertFalse(looks_thin_opener("Full-time"))

    def test_chip_tap_is_not_flagged(self):
        chips = ["Full-time", "Part-time", "Contract", "Other"]
        self.assertFalse(
            flag_onboarding_answer_for_followup(
                "What's your day-to-day setup?",
                "Full-time",
                suggested_responses=chips,
            )
        )
        self.assertTrue(
            flag_onboarding_answer_for_followup(
                "What's your day-to-day setup?",
                "fine",
                suggested_responses=chips,
            )
        )


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
        with mock.patch("api.utils.AI.AI.ask") as ask:
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
        ask.assert_not_called()
        entry = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertTrue(entry.needs_followup)
        self.assertEqual(entry.followup_prompt, "What is worrying you most right now?")
        self.assertEqual(response.json["entries"][0]["needs_followup"], True)

    def test_complete_does_not_call_gemini_for_specific_or_chips(self):
        self.q_worry.suggested_responses = ["Full-time", "Part-time", "Contract"]
        self.q_worry.save(update_fields=["suggested_responses"])
        with mock.patch("api.utils.AI.AI.ask") as ask:
            response = self._post(
                "/onboarding/answers",
                {
                    "variant": "initial",
                    "complete": True,
                    "answers": [
                        {
                            "knowledge_question_id": self.q_worry.id,
                            "value": "Full-time",
                        }
                    ],
                },
                self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        ask.assert_not_called()
        entry = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertFalse(entry.needs_followup)
        self.assertEqual(entry.followup_prompt, "")

    def test_placeholder_complete_does_not_classify(self):
        with mock.patch(
            "api.knowledge.followup.flag_onboarding_answer_for_followup"
        ) as skipped:
            complete = self._post("/onboarding/complete", {}, self.token)
        self.assertEqual(complete.status_code, status.HTTP_200_OK, complete.json)
        skipped.assert_not_called()
        placeholder = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertFalse(placeholder.needs_followup)

    def test_step_submit_does_not_classify(self):
        with mock.patch(
            "api.knowledge.followup.flag_onboarding_answer_for_followup"
        ) as skipped:
            response = self._post(
                "/onboarding/answers",
                {
                    "variant": "initial",
                    "complete": False,
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
        skipped.assert_not_called()
        entry = KnowledgeEntry.current_for(self.consumer, self.worry)
        self.assertFalse(entry.needs_followup)


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

    def _session_claimed_granted(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        self.consumer.onboarding_followup_consumed_at = timezone.now()
        self.consumer.onboarding_followup_session_id = session.id
        self.consumer.onboarding_followup_consent = (
            Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED
        )
        self.consumer.save(
            update_fields=[
                "onboarding_followup_consumed_at",
                "onboarding_followup_session_id",
                "onboarding_followup_consent",
            ]
        )
        activate_next_followup(self.consumer, session)
        session.refresh_from_db()
        self.consumer.refresh_from_db()
        session.consumer = self.consumer
        return session

    def test_today_does_not_greet_but_injects_block(self):
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            response = self._get("/sessions/today", access_token=self.token)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertIsNone(response.json["last_message"])
        self.consumer.refresh_from_db()
        self.assertIsNone(self.consumer.onboarding_followup_consumed_at)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 0)
        get_agent_response.assert_not_called()
        session = Session.objects.get(id=response.json["id"])
        session.consumer = self.consumer
        self.assertTrue(should_inject_onboarding_followup(session))
        block = format_onboarding_followup_block(session)
        self.assertIn("ONBOARDING_FOLLOW_UP", block)
        self.assertIn("stay_on_opener", block)
        self.assertIn("What is worrying you most?", block)

    def test_second_general_session_does_not_greet(self):
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            first = self._get("/sessions/today", access_token=self.token)
            self.assertEqual(first.status_code, status.HTTP_200_OK)
            second = self._post("/sessions", {}, access_token=self.token)

        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.json)
        self.assertIsNone(second.json["last_message"])
        get_agent_response.assert_not_called()

    def test_not_onboarded_does_not_consume_latch(self):
        self.consumer.onboarded = False
        self.consumer.save(update_fields=["onboarded"])
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        maybe_start_onboarding_followup(session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        user_message = Message.objects.create(
            session=session, sender=participant, text="Hello"
        )
        handle_onboarding_followup_reply(session, user_message)
        self.consumer.refresh_from_db()
        self.assertIsNone(self.consumer.onboarding_followup_consumed_at)

    def test_hello_asks_permission_without_gemini(self):
        today = self._get("/sessions/today", access_token=self.token)
        session_id = today.json["id"]
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            response = self._post(
                "/messages",
                {"text": "Hello", "session": session_id},
                access_token=self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        get_agent_response.assert_not_called()
        self.assertIn("stuff", response.json["text"])
        self.assertEqual(
            response.json["suggested_responses"],
            list(Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_CHIPS),
        )
        self.consumer.refresh_from_db()
        self.assertIsNotNone(self.consumer.onboarding_followup_consumed_at)
        self.assertEqual(self.consumer.onboarding_followup_session_id, session_id)
        self.assertEqual(
            self.consumer.onboarding_followup_consent,
            Constants.ONBOARDING_FOLLOWUP_CONSENT_PENDING,
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 0)

    def test_real_topic_skips_permission_and_closes_window(self):
        today = self._get("/sessions/today", access_token=self.token)
        session_id = today.json["id"]
        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = (
                GeneralResponse(
                    text="Tell me more about the presentation.",
                    reasoning="stay",
                    suggested_responses=[],
                ),
                {},
                None,
                None,
            )
            response = self._post(
                "/messages",
                {
                    "text": "I lie awake replaying a fight I had with my sister",
                    "session": session_id,
                },
                access_token=self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        get_agent_response.assert_called_once()
        self.assertEqual(response.json["text"], "Tell me more about the presentation.")
        self.consumer.refresh_from_db()
        self.assertEqual(
            self.consumer.onboarding_followup_consent,
            Constants.ONBOARDING_FOLLOWUP_CONSENT_DECLINED,
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 0)
        self.assertTrue(self.entry.needs_followup)
        session = Session.objects.get(id=session_id)
        session.consumer = self.consumer
        self.assertFalse(should_inject_onboarding_followup(session))

    def test_permission_yes_activates_followup(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        hello = Message.objects.create(session=session, sender=participant, text="Hi")
        handle_onboarding_followup_reply(session, hello)
        self.consumer.refresh_from_db()
        session.consumer = self.consumer
        yes = Message.objects.create(
            session=session,
            sender=participant,
            text=Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_YES,
        )
        result = handle_onboarding_followup_reply(session, yes)
        self.assertIsNone(result.canned_text)
        self.consumer.refresh_from_db()
        self.assertEqual(
            self.consumer.onboarding_followup_consent,
            Constants.ONBOARDING_FOLLOWUP_CONSENT_GRANTED,
        )
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 1)

    def test_permission_no_declines(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        hello = Message.objects.create(session=session, sender=participant, text="Hi")
        handle_onboarding_followup_reply(session, hello)
        self.consumer.refresh_from_db()
        session.consumer = self.consumer
        no = Message.objects.create(
            session=session,
            sender=participant,
            text=Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_NO,
        )
        result = handle_onboarding_followup_reply(session, no)
        self.assertEqual(
            result.canned_text, Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_DECLINE_ACK
        )
        self.consumer.refresh_from_db()
        self.assertEqual(
            self.consumer.onboarding_followup_consent,
            Constants.ONBOARDING_FOLLOWUP_CONSENT_DECLINED,
        )
        session.consumer = self.consumer
        self.assertFalse(should_inject_onboarding_followup(session))

    def test_first_real_topic_is_not_classified_as_followup_answer(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        user_message = Message.objects.create(
            session=session,
            sender=participant,
            text="I lie awake replaying a fight I had with my sister",
        )
        with mock.patch("api.knowledge.followup.is_answer_vague") as classify:
            result = handle_onboarding_followup_reply(session, user_message)
        classify.assert_not_called()
        self.assertTrue(result.decline_after_agent)
        self.assertIsNone(result.canned_text)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.followup_attempts, 0)
        self.assertTrue(self.entry.needs_followup)

    def test_typed_specific_during_permission_is_the_answer(self):
        session = Session.objects.create(consumer=self.consumer)
        Participant.create_participants(session=session)
        participant = Participant.objects.filter(
            session=session, consumer=self.consumer
        ).first()
        hello = Message.objects.create(session=session, sender=participant, text="Hi")
        handle_onboarding_followup_reply(session, hello)
        self.consumer.refresh_from_db()
        session.consumer = self.consumer
        specific = Message.objects.create(
            session=session,
            sender=participant,
            text="I lie awake replaying a fight I had with my sister",
        )
        with mock.patch("api.knowledge.followup.is_answer_vague", return_value=False):
            result = handle_onboarding_followup_reply(session, specific)
        self.assertIsNone(result.canned_text)
        current = KnowledgeEntry.current_for(self.consumer, self.field)
        self.assertEqual(current.value, specific.text)
        self.assertFalse(current.needs_followup)

    def test_specific_reply_writes_new_entry(self):
        session = self._session_claimed_granted()
        self.assertTrue(is_onboarding_followup_session(session))
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
        session = self._session_claimed_granted()
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

    def test_unsaved_message_is_not_classified(self):
        session = self._session_claimed_granted()
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

    def test_message_api_sends_direct_reask_after_grant(self):
        today = self._get("/sessions/today", access_token=self.token)
        session_id = today.json["id"]
        hello = self._post(
            "/messages",
            {"text": "Hello", "session": session_id},
            access_token=self.token,
        )
        self.assertEqual(hello.status_code, status.HTTP_201_CREATED, hello.json)

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = (
                GeneralResponse(text="What's that about?", reasoning="x", suggested_responses=[]),
                {},
                None,
                None,
            )
            granted = self._post(
                "/messages",
                {
                    "text": Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_YES,
                    "session": session_id,
                },
                access_token=self.token,
            )
        self.assertEqual(granted.status_code, status.HTTP_201_CREATED, granted.json)
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
