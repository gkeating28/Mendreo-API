from unittest.mock import patch

from django.test import SimpleTestCase

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse
from ...utils.SessionStateMachine import is_model_ready_chip, on_model_turn, prepare_model_readiness
from ...utils.turn_hint import user_prompt_with_hint
from ..utils.BaseTest import BaseTest
from ..utils.manager import General


class ReadyChipTests(SimpleTestCase):
    def test_advance_phrases_match_and_content_chips_do_not(self):
        for chip in (
            "I'm ready to continue",
            "Yes, I'm ready",
            "I'm ready",
            "I'm ready...",
            "Not yet",
            "Finish exercise",
            "Finish the exercise",
            "I'm ready for the next step",
            "Ready to proceed",
            "Yes, let's start",
            "Let's continue",
            "next step",
        ):
            self.assertTrue(is_model_ready_chip(chip), chip)

        self.assertFalse(
            is_model_ready_chip("I'm ready to try the breath work tonight")
        )
        self.assertFalse(is_model_ready_chip("Start with the deadline"))

    def test_prepare_model_readiness_drops_continue_chip(self):
        session = Session(state=Constants.SESSION_STATE_STEP_ACTIVE, current_step_no=0)
        response = ExerciseStateResponse(
            text="What is the worry?",
            reasoning="test",
            suggested_responses=[],
            step_goal_met=False,
            asks_readiness=False,
        )
        kind, chips = prepare_model_readiness(
            session,
            response,
            Constants.QUESTION_KIND_OPEN,
            ["I'm ready to continue", "Work deadlines..."],
            "What is the worry?",
        )
        self.assertEqual(kind, Constants.QUESTION_KIND_OPEN)
        self.assertEqual(chips, ["Work deadlines..."])


class GoalGateTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def _session(self, *, done_when="The user has named the worry and the situation.", depth=False):
        exercise = General.create_exercise()
        exercise.steps.all().delete()
        exercise.depth_check = depth
        exercise.steps_no = 1
        exercise.save(update_fields=["depth_check", "steps_no", "updated_at"])
        Step.objects.create(
            exercise=exercise,
            title="Name it",
            description="Describe it",
            instructions="Ask what the worry is.",
            completion_label="Named",
            completion_prompt="Summarise the worry." if depth else None,
            done_when=done_when,
            order=0,
        )
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=1,
            total_steps_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        SessionStep.create(session, exercise)
        Participant.create_participants(session)
        return session

    def _reply(self, session, *, goal=True, asks=True):
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(
            session=session,
            sender=agent,
            text="Are you ready for the next step?",
            reasoning="test",
            question_kind=Constants.QUESTION_KIND_READINESS,
            suggested_responses=[],
        )
        response = ExerciseStateResponse(
            text=message.text,
            reasoning="test",
            suggested_responses=[],
            step_goal_met=goal,
            asks_readiness=asks,
            question_kind=Constants.QUESTION_KIND_READINESS,
        )
        return message, response

    def test_rejected_goal_does_not_advance_and_hints_the_gap(self):
        session = self._session()
        message, response = self._reply(session)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            on_model_turn(session, message, response)

        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        message.refresh_from_db()
        self.assertIsNone(step.goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(message.question_kind, Constants.QUESTION_KIND_OPEN)
        self.assertIn("the situation", session.cached_prompt_meta["goal_hint"])

        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="ok")
        prompted = user_prompt_with_hint(session, user_message)
        self.assertIn("the situation", prompted)
        self.assertNotIn("<TURN_HINT>", user_message.text)
        session.refresh_from_db()
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})

    def test_passed_goal_with_readiness_waits_for_the_chip(self):
        session = self._session()
        message, response = self._reply(session)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, message, response)

        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        message.refresh_from_db()
        self.assertIsNotNone(step.goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(message.question_kind, Constants.QUESTION_KIND_READINESS)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_FINISH, Constants.CHIP_NOT_YET],
        )

    def test_checker_exception_accepts_the_claim(self):
        session = self._session()
        message, response = self._reply(session)
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=RuntimeError("down"),
        ):
            on_model_turn(session, message, response)

        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertIsNotNone(step.goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)

    def test_empty_done_when_accepts_without_a_check(self):
        session = self._session(done_when="")
        message, response = self._reply(session)
        with patch("api.utils.extraction.AI.ask") as ask:
            on_model_turn(session, message, response)
        ask.assert_not_called()
        session.refresh_from_db()
        self.assertIsNotNone(session.session_steps.get(order=0).goal_met_at)

    def test_failed_depth_check_does_not_stamp_the_goal(self):
        session = self._session(depth=True)
        message, response = self._reply(session)
        with (
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": True, "missing": ""},
            ),
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "a worry", "confidence": 0.1},
            ),
        ):
            on_model_turn(session, message, response)

        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        message.refresh_from_db()
        self.assertIsNone(step.goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(message.question_kind, Constants.QUESTION_KIND_OPEN)
        self.assertEqual(session.cached_prompt_meta["depth_hint_step_id"], step.id)
