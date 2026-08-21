from unittest import mock

from django.test import override_settings
from rest_framework import status

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...tests.TestCase import TestCase
from ...utils import Constants
from ...utils.Agent import GeneralResponse
from ..utils import Data
from ..utils.manager import Auth, General


class ExerciseOfferTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.exercise = General.create_exercise()
        self.exercise.status = Constants.EXERCISE_STATUS_PUBLISHED
        self.exercise.save(update_fields=["status"])
        self.session = General.create_session(consumer=self.consumer)

    def _agent_participant(self):
        return Participant.objects.filter(
            session=self.session,
            agent=self.consumer.agent,
        ).first()

    def _consumer_participant(self):
        return Participant.objects.filter(
            session=self.session,
            consumer=self.consumer,
        ).first()

    def _create_offer(self, suggested_responses=None):
        if suggested_responses is None:
            suggested_responses = list(Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES)
        return Message.objects.create(
            session=self.session,
            sender=self._agent_participant(),
            text=f"Would you like to start {self.exercise.title}?",
            exercise=self.exercise,
            suggested_responses=suggested_responses,
            reasoning="triage",
        )

    def _post_message(self, text, from_suggested_response=None):
        data = Data.valid_message_data(text=text, session=self.session)
        if from_suggested_response is not None:
            data["from_suggested_response"] = from_suggested_response
        return self._post("/messages", data, access_token=self.access_token)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_offer_message_includes_yes_no_chips(self):
        mocked = GeneralResponse(
            text="There's an exercise that fits.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message("I've been stuck in the same thought loop")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertIn("Would you like to start an exercise? Yes or no.", response.json["text"])
        self.assertIn(self.exercise.title, response.json["text"])
        self.assertEqual(response.json["exercise"]["id"], self.exercise.id)
        self.assertIsNone(response.json["exercise_session"])
        self.session.refresh_from_db()
        self.assertIsNone(self.session.exercise_id)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_offer_keeps_lets_work_through_copy_and_only_adds_chips(self):
        mocked = GeneralResponse(
            text=f"Let's work through '{self.exercise.title}'. Tap below to start when you're ready.",
            reasoning="Unified Protocol",
            suggested_responses=["Tell me more"],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, self.exercise
            response = self._post_message(f"Try '{self.exercise.title}'")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json["suggested_responses"],
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertIn("Let's work through", response.json["text"])
        self.assertNotIn(
            "There's an exercise that fits what you're describing",
            response.json["text"],
        )
        self.assertEqual(response.json["exercise"]["id"], self.exercise.id)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_yes_chip_saves_message_only_and_does_not_start_session(self):
        offer = self._create_offer()

        with mock.patch("api.message.views.request_agent_response") as ai:
            response = self._post_message("Yes", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ai.assert_not_called()
        self.assertEqual(response.json["text"], "Yes")
        self.assertIsNotNone(response.json["sender"]["consumer"])
        self.assertIsNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])

        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.last_message_id, response.json["id"])

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_typed_yes_is_normal_chat(self):
        offer = self._create_offer()
        mocked = GeneralResponse(
            text="I'm here — take your time.",
            reasoning="continue",
            suggested_responses=[],
        )

        with mock.patch("api.utils.Agent.get_response") as get_agent_response:
            get_agent_response.return_value = mocked, {}, None, None
            response = self._post_message("Yes")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json["text"], "I'm here — take your time.")
        self.assertIsNotNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(
            offer.suggested_responses,
            Constants.EXERCISE_OFFER_SUGGESTED_RESPONSES,
        )
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_no_chip_clears_pills_and_keeps_saved_offer(self):
        offer = self._create_offer()

        with mock.patch("api.message.views.request_agent_response") as ai:
            response = self._post_message("No", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ai.assert_not_called()
        self.assertIn("I'll leave", response.json["text"])
        self.assertIsNotNone(response.json["sender"]["agent"])

        offer.refresh_from_db()
        self.assertEqual(offer.suggested_responses, [])
        self.assertEqual(offer.exercise_id, self.exercise.id)
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertEqual(offer_payload["exercise"]["id"], self.exercise.id)
        self.assertEqual(offer_payload["suggested_responses"], [])
        self.assertIsNone(offer_payload["exercise_session"])

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_sheet_decline_after_yes_does_not_start_session(self):
        offer = self._create_offer()
        self._post_message("Yes", from_suggested_response=True)

        with mock.patch("api.message.views.request_agent_response") as ai:
            response = self._post_message("No", from_suggested_response=True)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        ai.assert_not_called()
        offer.refresh_from_db()
        self.assertEqual(offer.exercise_id, self.exercise.id)
        self.assertFalse(
            Session.objects.filter(
                consumer=self.consumer,
                exercise=self.exercise,
            ).exists()
        )

    def test_exercise_session_payload_reuses_paused_and_completed(self):
        offer = self._create_offer(suggested_responses=[])

        exercise_session = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=False,
            current_step_no=2,
            total_steps_no=self.exercise.steps_no,
        )

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertEqual(offer_payload["exercise_session"]["id"], exercise_session.id)
        self.assertFalse(offer_payload["exercise_session"]["completed"])

        exercise_session.completed = True
        exercise_session.save(update_fields=["completed"])

        listed = self._get(
            f"/messages?session_id={self.session.id}&order_by=created_at",
            access_token=self.access_token,
        )
        offer_payload = next(
            row for row in listed.json["results"] if row["id"] == offer.id
        )
        self.assertTrue(offer_payload["exercise_session"]["completed"])
        self.assertEqual(offer_payload["exercise_session"]["id"], exercise_session.id)
