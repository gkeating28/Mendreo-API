from contextlib import contextmanager
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse
from ...utils.SessionStateMachine import confirm_summary_if_done, on_model_turn
from ...utils.summary_confirmation import (
    SUMMARY_CONFIRM_EXPECT_STEP,
    SUMMARY_CONFIRM_MESSAGE_ID,
    is_summary_confirmation,
    summary_was_confirmed,
)
from ...utils.turn_hint import SUMMARY_CONFIRM_HINT
from ..utils.BaseTest import BaseTest
from ..utils.manager import General

_DONE_WHEN = "The user confirmed the summary is accurate."
_SUMMARY = (
    "You are worried about losing your job because of layoffs. "
    "Have I captured that accurately?"
)
_PHRASE_SUMMARY = (
    "So, to recap, you worry about missing deadlines and losing your job, "
    "and it comes up at night when you are alone. Did I capture that accurately?"
)
_GOT_IT = (
    "You are worried about losing your job because of layoffs, "
    "which makes it hard to switch off at night. "
    "Have I got that right, indeed?"
)


class _SummaryFixture(BaseTest):
    def endpoint(self):
        return "messages"

    def _session(self, *, steps=2):
        exercise = General.create_exercise()
        exercise.steps.all().delete()
        exercise.depth_check = False
        exercise.steps_no = steps
        exercise.save(update_fields=["depth_check", "steps_no", "updated_at"])
        for order in range(steps):
            Step.objects.create(
                exercise=exercise,
                title=f"Step {order + 1}",
                description="Describe it",
                instructions="Ask what is going on.",
                order=order,
                done_when=_DONE_WHEN,
            )
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=1,
            total_steps_no=steps,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        SessionStep.create(session, exercise)
        Participant.create_participants(session)
        return session

    def _agent(self, session):
        return Participant.objects.filter(session=session, agent__isnull=False).first()

    def _turn(self, session, text, *, goal=False, asks=False, chips=None):
        message = Message.objects.create(
            session=session,
            sender=self._agent(session),
            text=text,
            reasoning="test",
            suggested_responses=list(chips or []),
            suggested_responses_kind=Constants.SUGGESTED_RESPONSES_KIND_FREE,
        )
        response = ExerciseStateResponse(
            text=text,
            reasoning="test",
            suggested_responses=list(chips or []),
            step_goal_met=goal,
            asks_readiness=asks,
            question_kind=Constants.QUESTION_KIND_NONE,
        )
        on_model_turn(session, message, response)
        session.refresh_from_db()
        message.refresh_from_db()
        return message

    def _hold_summary(self, session, chips=None):
        """The summary question itself is held, with no later summary after it."""
        message = self._turn(
            session,
            _SUMMARY,
            goal=True,
            asks=True,
            chips=chips,
        )
        self.assertEqual(session.cached_prompt_meta["goal_hint"], SUMMARY_CONFIRM_HINT)
        self.assertEqual(
            str(session.cached_prompt_meta[SUMMARY_CONFIRM_MESSAGE_ID]),
            str(message.id),
        )
        self.assertNotIn(SUMMARY_CONFIRM_EXPECT_STEP, session.cached_prompt_meta)
        return message

    def _unmarked_summary(self, session, text=_GOT_IT):
        """A summary question the model did not claim was done, so nothing is marked."""
        self.assertTrue(is_summary_confirmation(text))
        return Message.objects.create(
            session=session,
            sender=self._agent(session),
            text=text,
            reasoning="test",
        )

    def _user(self, session, text):
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        return Message.objects.create(session=session, sender=user, text=text)

    def _assert_open(self, session):
        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertFalse(step.completed)
        self.assertEqual(session.current_step_no, 1)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def _assert_advanced(self, session):
        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertTrue(step.completed)
        self.assertEqual(session.current_step_no, 2)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def _quiet(self):
        return _quiet_models()


@override_settings(AI_ASYNC_MESSAGES=False)
class StructuralSummaryConfirmTests(_SummaryFixture):
    def test_held_summary_then_typed_yes_completes_on_the_first_yes(self):
        session = self._session()
        with self._quiet():
            self._hold_summary(session)
            outcome = confirm_summary_if_done(self._user(session, "yes"))
        self.assertIsNotNone(outcome)
        self._assert_advanced(session)

    def test_tapped_yes_thats_right_completes_the_held_summary(self):
        session = self._session()
        with self._quiet() as (greeting, chat, queued):
            self._hold_summary(session, chips=["Yes, that's right"])
            response = self._post(
                "/messages",
                {
                    "session": session.id,
                    "text": "Yes, that's right",
                    "from_suggested_response": True,
                },
                self.consumer_one_access_token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        greeting.assert_called_once()
        chat.assert_not_called()
        queued.assert_not_called()
        self._assert_advanced(session)

    def test_tapped_tell_me_more_does_not_complete_the_step(self):
        session = self._session()
        with self._quiet() as (greeting, chat, queued):
            self._hold_summary(session, chips=["Tell me more"])
            response = self._post(
                "/messages",
                {
                    "session": session.id,
                    "text": "Tell me more",
                    "from_suggested_response": True,
                },
                self.consumer_one_access_token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        greeting.assert_not_called()
        chat.assert_called_once()
        queued.assert_not_called()
        self._assert_open(session)

    def test_a_correction_does_not_complete_the_step(self):
        session = self._session()
        with self._quiet() as (greeting, chat, queued):
            self._hold_summary(session)
            typed = confirm_summary_if_done(
                self._user(session, "no, it's also about money")
            )
            response = self._post(
                "/messages",
                {
                    "session": session.id,
                    "text": "no, it's also about money",
                    "from_suggested_response": True,
                },
                self.consumer_one_access_token,
            )
        self.assertIsNone(typed)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        greeting.assert_not_called()
        chat.assert_called_once()
        queued.assert_not_called()
        self._assert_open(session)

    def test_a_non_question_hold_marks_the_next_question(self):
        session = self._session()
        with self._quiet():
            self._turn(session, "We have covered what this step asked for.", goal=True)
            self.assertEqual(session.cached_prompt_meta[SUMMARY_CONFIRM_EXPECT_STEP], 1)
            self.assertNotIn(SUMMARY_CONFIRM_MESSAGE_ID, session.cached_prompt_meta)
            summary = self._turn(session, _SUMMARY)
            self.assertEqual(
                str(session.cached_prompt_meta[SUMMARY_CONFIRM_MESSAGE_ID]),
                str(summary.id),
            )
            outcome = confirm_summary_if_done(self._user(session, "yes"))
        self.assertIsNotNone(outcome)
        self._assert_advanced(session)

    def test_phrase_fallback_still_completes_on_an_exact_yes(self):
        session = self._session()
        with self._quiet():
            self._turn(session, _PHRASE_SUMMARY)
            self.assertNotIn(SUMMARY_CONFIRM_MESSAGE_ID, session.cached_prompt_meta or {})
            outcome = confirm_summary_if_done(self._user(session, "yes"))
        self.assertIsNotNone(outcome)
        self._assert_advanced(session)

    def test_an_unmarked_summary_accepts_yes_that_is_right(self):
        for reply in ("Yes, that is right", "yes"):
            session = self._session()
            with self._quiet():
                self._unmarked_summary(session)
                self.assertNotIn(
                    SUMMARY_CONFIRM_MESSAGE_ID, session.cached_prompt_meta or {}
                )
                outcome = confirm_summary_if_done(self._user(session, reply))
            self.assertIsNotNone(outcome, reply)
            self._assert_advanced(session)

    def test_an_unmarked_summary_refuses_a_correction(self):
        for reply in ("no, it's also about money", "yes but change the second part"):
            session = self._session()
            with self._quiet():
                self._unmarked_summary(session)
                outcome = confirm_summary_if_done(self._user(session, reply))
            self.assertIsNone(outcome, reply)
            self._assert_open(session)

    def test_an_unmarked_summary_stays_open_when_done_when_is_not_met(self):
        session = self._session()
        with self._quiet():
            self._unmarked_summary(session)
            with patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "a time"},
            ) as checker:
                outcome = confirm_summary_if_done(self._user(session, "Yes, that is right"))
        checker.assert_called_once()
        self.assertIsNone(outcome)
        self._assert_open(session)

    def test_an_unmarked_summary_does_not_complete_the_last_step(self):
        session = self._session(steps=1)
        with self._quiet() as (greeting, _chat, _queued):
            self._unmarked_summary(session)
            outcome = confirm_summary_if_done(self._user(session, "Yes, that is right"))
        self.assertIsNone(outcome)
        greeting.assert_not_called()
        self._assert_open(session)

    def test_last_step_stays_open(self):
        session = self._session(steps=1)
        with self._quiet() as (greeting, chat, _queued):
            self._hold_summary(session)
            outcome = confirm_summary_if_done(self._user(session, "yes"))
            chip = self._post(
                "/messages",
                {
                    "session": session.id,
                    "text": "Yes, that's right",
                    "from_suggested_response": True,
                },
                self.consumer_one_access_token,
            )
        self.assertIsNone(outcome)
        self.assertEqual(chip.status_code, status.HTTP_201_CREATED, chip.json)
        greeting.assert_not_called()
        chat.assert_called_once()
        self._assert_open(session)
        self.assertFalse(
            summary_was_confirmed(session, session.session_steps.get(order=0).step)
        )


@contextmanager
def _quiet_models():
    with (
        patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ),
        patch(
            "api.utils.AIWorkerClient.request_session_greeting",
            return_value=None,
        ) as greeting,
        patch(
            "api.message.views.request_agent_response",
            side_effect=lambda user_message, session: user_message,
        ) as chat,
        patch("api.message.views.enqueue_agent_response") as queued,
        patch("api.utils.extraction.judge_ready_reply", return_value="other"),
    ):
        yield greeting, chat, queued
