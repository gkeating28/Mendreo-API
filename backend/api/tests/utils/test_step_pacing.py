from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework import status

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse
from ...utils.SessionStateMachine import (
    confirm_readiness_reply,
    confirm_summary_if_done,
    consume_chip,
    is_model_ready_chip,
    on_model_turn,
    prepare_model_readiness,
)
from ...utils.summary_confirmation import is_summary_confirmation, summary_confirmation_rule
from ...utils.turn_hint import SUMMARY_CONFIRM_HINT, user_prompt_with_hint
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
        message.text = "The worry is the presentation deadline."
        message.save(update_fields=["text", "updated_at"])
        response.text = message.text
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

    def test_step_decision_records_met_rejected_and_no_readiness(self):
        session = self._session()
        met_message, met_response = self._reply(session)
        met_message.usage = {"input_tokens": 5, "output_tokens": 2}
        met_message.save(update_fields=["usage", "updated_at"])
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, met_message, met_response)
        met_message.refresh_from_db()
        met = met_message.usage["step_decision"]
        self.assertEqual(met_message.usage["input_tokens"], 5)
        self.assertEqual(met_message.usage["output_tokens"], 2)
        self.assertEqual(met["step_no"], 1)
        self.assertEqual(met["model"], {"step_goal_met": True, "asks_readiness": True})
        self.assertEqual(met["accepted"], {"step_goal_met": True, "asks_readiness": True})
        self.assertEqual(met["check_done_when"], {"met": True, "missing": ""})
        self.assertIsNone(met["goal_hint"])

        session = self._session()
        rejected, rejected_response = self._reply(session)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            on_model_turn(session, rejected, rejected_response)
        rejected.refresh_from_db()
        gap = rejected.usage["step_decision"]
        self.assertEqual(gap["model"], {"step_goal_met": True, "asks_readiness": True})
        self.assertEqual(gap["accepted"], {"step_goal_met": False, "asks_readiness": False})
        self.assertEqual(gap["check_done_when"], {"met": False, "missing": "the situation"})
        self.assertIn("the situation", gap["goal_hint"])

        session = self._session()
        quiet, quiet_response = self._reply(session, goal=False, asks=False)
        quiet.text = "Noted."
        quiet.save(update_fields=["text", "updated_at"])
        with patch("api.utils.extraction.check_done_when") as checker:
            on_model_turn(session, quiet, quiet_response)
        checker.assert_not_called()
        quiet.refresh_from_db()
        none = quiet.usage["step_decision"]
        self.assertEqual(
            none["model"], {"step_goal_met": False, "asks_readiness": False}
        )
        self.assertEqual(
            none["accepted"], {"step_goal_met": False, "asks_readiness": False}
        )
        self.assertIsNone(none["check_done_when"])
        self.assertIsNone(none["goal_hint"])

    def test_token_totals_ignore_step_decision(self):
        from ...utils.Agent import update_session

        session = self._session()
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(
            session=session,
            sender=agent,
            text="Noted.",
            usage={
                "input_tokens": 5,
                "output_tokens": 2,
                "step_decision": {"step_no": 1},
            },
        )
        with patch("api.utils.Agent.AI.ask", return_value={}):
            update_session("prompt", session)
        session.refresh_from_db()
        message.refresh_from_db()
        self.assertNotIn("step_decision", session.usage)
        self.assertIsInstance(session.usage["input_tokens"], int)
        self.assertEqual(message.usage["input_tokens"], 5)
        self.assertEqual(message.usage["step_decision"]["step_no"], 1)

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

    def test_confirmation_question_does_not_accept_the_goal(self):
        session = self._session()
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(
            session=session,
            sender=agent,
            text="Did I capture that accurately?",
            reasoning="test",
        )
        response = ExerciseStateResponse(
            text=message.text,
            reasoning="test",
            suggested_responses=[],
            step_goal_met=True,
            asks_readiness=False,
        )
        with patch("api.utils.extraction.check_done_when") as check:
            on_model_turn(session, message, response)
        check.assert_not_called()
        session.refresh_from_db()
        self.assertIsNone(session.session_steps.get(order=0).goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def test_yep_completes_the_step_when_done_when_is_met(self):
        session = self._session()
        exercise = session.exercise
        exercise.steps_no = 2
        exercise.save(update_fields=["steps_no", "updated_at"])
        next_step = Step.objects.create(
            exercise=exercise,
            title="Next",
            description="Next",
            instructions="Ask for a plan.",
            order=1,
        )
        SessionStep.objects.create(
            session=session,
            step=next_step,
            order=1,
            completed=False,
        )
        session.total_steps_no = 2
        session.save(update_fields=["total_steps_no", "updated_at"])
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="Yep")
        with (
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": True, "missing": ""},
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
        ):
            outcome = confirm_summary_if_done(user_message)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        self.assertTrue(session.session_steps.get(order=0).completed)
        self.assertEqual(session.current_step_no, 2)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def test_yep_stays_in_chat_when_done_when_is_not_met(self):
        session = self._session()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="Yep")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            outcome = confirm_summary_if_done(user_message)
        self.assertIsNone(outcome)
        session.refresh_from_db()
        self.assertFalse(session.session_steps.get(order=0).completed)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def test_ready_to_continue_does_not_finish_a_step_that_must_name_the_worry(self):
        session = self._session(
            done_when=(
                "The user has described their specific worry, the situation it occurs in, "
                "and confirmed the summary is accurate."
            )
        )
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(
            session=session,
            sender=agent,
            text=(
                "The straw breathing made the thought, 'I'm going to miss a deadline "
                "and lose my job,' feel less strong. We've reached the end of this step. "
                "Are you ready to continue?"
            ),
            reasoning="test",
            question_kind=Constants.QUESTION_KIND_READINESS,
        )
        response = ExerciseStateResponse(
            text=message.text,
            reasoning="test",
            suggested_responses=[],
            step_goal_met=True,
            asks_readiness=True,
            question_kind=Constants.QUESTION_KIND_READINESS,
        )
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, message, response)

        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertIsNone(step.goal_met_at)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(session.cached_prompt_meta["goal_hint"], SUMMARY_CONFIRM_HINT)

    def test_yep_after_a_named_summary_completes_the_step(self):
        session = self._session(
            done_when="The user confirmed the summary is accurate.",
        )
        exercise = session.exercise
        exercise.steps_no = 2
        exercise.save(update_fields=["steps_no", "updated_at"])
        next_step = Step.objects.create(
            exercise=exercise,
            title="Next",
            description="Next",
            instructions="Ask for a plan.",
            order=1,
        )
        SessionStep.objects.create(session=session, step=next_step, order=1, completed=False)
        session.total_steps_no = 2
        session.save(update_fields=["total_steps_no", "updated_at"])
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        Message.objects.create(
            session=session,
            sender=agent,
            text=(
                "So, to recap, you worry about missing deadlines and losing your job, "
                "and it comes up at night when you are alone. Did I capture that accurately?"
            ),
            reasoning="test",
        )
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="Yep")
        with (
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": True, "missing": ""},
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
        ):
            outcome = confirm_summary_if_done(user_message)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        self.assertTrue(session.session_steps.get(order=0).completed)

    def test_yep_after_a_readiness_question_does_not_confirm_the_summary(self):
        session = self._session(
            done_when="The user confirmed the summary is accurate.",
        )
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        Message.objects.create(
            session=session,
            sender=agent,
            text="We've reached the end of this step. Are you ready to continue?",
            reasoning="test",
        )
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="Yep")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ) as check:
            outcome = confirm_summary_if_done(user_message)
        self.assertIsNone(outcome)
        check.assert_not_called()
        session.refresh_from_db()
        self.assertFalse(session.session_steps.get(order=0).completed)

    def _two_steps(self):
        session = self._session(
            done_when=(
                "The user has described their specific worry, the situation it occurs in, "
                "and confirmed the summary is accurate."
            )
        )
        exercise = session.exercise
        exercise.steps_no = 2
        exercise.save(update_fields=["steps_no", "updated_at"])
        next_step = Step.objects.create(
            exercise=exercise,
            title="Next",
            description="Next",
            instructions="Ask for a plan.",
            order=1,
        )
        SessionStep.objects.create(
            session=session,
            step=next_step,
            order=1,
            completed=False,
        )
        session.total_steps_no = 2
        session.save(update_fields=["total_steps_no", "updated_at"])
        return session

    def _ask(self, session, text):
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        return Message.objects.create(
            session=session,
            sender=agent,
            text=text,
            reasoning="test",
        )

    def _plain_two_steps(self):
        session = self._session()
        exercise = session.exercise
        exercise.steps_no = 2
        exercise.save(update_fields=["steps_no", "updated_at"])
        next_step = Step.objects.create(
            exercise=exercise,
            title="Next",
            description="Next",
            instructions="Ask for a plan.",
            order=1,
        )
        SessionStep.objects.create(
            session=session,
            step=next_step,
            order=1,
            completed=False,
        )
        session.total_steps_no = 2
        session.save(update_fields=["total_steps_no", "updated_at"])
        return session

    def _claimed_without_flag(self, session, text):
        message = self._ask(session, text)
        message.question_kind = Constants.QUESTION_KIND_NONE
        message.suggested_responses = []
        message.save(update_fields=["question_kind", "suggested_responses", "updated_at"])
        response = ExerciseStateResponse(
            text=text,
            reasoning="test",
            suggested_responses=[],
            step_goal_met=True,
            asks_readiness=False,
            question_kind=Constants.QUESTION_KIND_NONE,
        )
        return message, response

    def test_readiness_wording_without_the_flag_runs_the_check(self):
        session = self._plain_two_steps()
        message, response = self._claimed_without_flag(
            session, "Are you ready to wrap up?"
        )
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ) as checker:
            on_model_turn(session, message, response)
        checker.assert_called_once()
        session.refresh_from_db()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertEqual(decision["model"]["asks_readiness"], False)
        self.assertTrue(decision["inferred_asks_readiness"])
        self.assertEqual(decision["accepted"]["asks_readiness"], True)
        self.assertEqual(decision["check_done_when"], {"met": True, "missing": ""})
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})

    def test_inferred_readiness_stores_a_hint_when_the_check_fails(self):
        session = self._plain_two_steps()
        message, response = self._claimed_without_flag(
            session, "The worry is the presentation deadline."
        )
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the location"},
        ):
            on_model_turn(session, message, response)
        session.refresh_from_db()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertFalse(decision["inferred_asks_readiness"])
        self.assertFalse(decision["accepted"]["asks_readiness"])
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(message.suggested_responses, [])
        self.assertIn("the location", session.cached_prompt_meta["goal_hint"])
        self.assertEqual(session.cached_prompt_meta["done_when_rejections"], {"1": 1})

    def test_readiness_question_keeps_the_chip_when_done_when_fails(self):
        session = self._plain_two_steps()
        message, response = self._claimed_without_flag(
            session, "You named the worry. Are you ready to continue?"
        )
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the location"},
        ) as checker:
            on_model_turn(session, message, response)
        checker.assert_called_once()
        session.refresh_from_db()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertTrue(decision["inferred_asks_readiness"])
        self.assertTrue(decision["accepted"]["asks_readiness"])
        self.assertEqual(decision["check_done_when"], {"met": False, "missing": "the location"})
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})

    def test_third_done_when_check_is_forced_after_two_rejections(self):
        session = self._plain_two_steps()
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the location"},
        ) as checker:
            for text in (
                "The worry is the presentation deadline.",
                "The situation is still missing.",
            ):
                message, response = self._claimed_without_flag(session, text)
                on_model_turn(session, message, response)
            session.refresh_from_db()
            self.assertEqual(session.cached_prompt_meta["done_when_rejections"], {"1": 2})
            self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
            third, third_response = self._claimed_without_flag(
                session, "Both parts are named now."
            )
            third_response.asks_readiness = True
            on_model_turn(session, third, third_response)
        self.assertEqual(checker.call_count, 2)
        session.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(
            third.usage["step_decision"]["check_done_when"],
            {"met": True, "missing": "", "forced": True},
        )
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(
            third.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )

    def test_a_first_pass_does_not_force_or_count_a_rejection(self):
        session = self._session()
        message, response = self._reply(session)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ) as checker:
            on_model_turn(session, message, response)
        checker.assert_called_once()
        session.refresh_from_db()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertEqual(decision["check_done_when"], {"met": True, "missing": ""})
        self.assertTrue(decision["model"]["asks_readiness"])
        self.assertTrue(decision["inferred_asks_readiness"])
        self.assertNotIn("forced", decision["check_done_when"])
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)

    def test_done_when_rejection_count_clears_when_the_step_advances(self):
        session = self._plain_two_steps()
        session.cached_prompt_meta = {"done_when_rejections": {"1": 2}, "goal_hint": "old"}
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        message, response = self._claimed_without_flag(
            session, "Both parts are named now."
        )
        response.asks_readiness = True
        with patch("api.utils.extraction.check_done_when") as checker:
            on_model_turn(session, message, response)
        checker.assert_not_called()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(
            session=session, sender=user, text=Constants.CHIP_READY_YES
        )
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "the worry", "confidence": 0.8},
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
        ):
            outcome = consume_chip(user_message, True)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        self.assertEqual(session.current_step_no, 2)
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})

    def test_a_plain_question_does_not_infer_readiness(self):
        session = self._plain_two_steps()
        message, response = self._claimed_without_flag(session, "What is the worry?")
        with patch("api.utils.extraction.check_done_when") as checker:
            on_model_turn(session, message, response)
        checker.assert_not_called()
        session.refresh_from_db()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertFalse(decision["model"]["asks_readiness"])
        self.assertFalse(decision["inferred_asks_readiness"])
        self.assertIsNone(decision["check_done_when"])
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(message.suggested_responses, [])

    def test_ready_to_put_this_strategy_into_practice_is_inferred(self):
        session = self._plain_two_steps()
        text = (
            "To wrap up, your strategy is to rely on the facts of your solid "
            "performance and to review your tasks before bed. Are you ready to "
            "put this strategy into practice?"
        )
        message, response = self._claimed_without_flag(session, text)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ) as checker:
            on_model_turn(session, message, response)
        checker.assert_called_once()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertFalse(decision["model"]["asks_readiness"])
        self.assertTrue(decision["inferred_asks_readiness"])

    def test_ready_to_explore_is_not_inferred(self):
        session = self._plain_two_steps()
        message, response = self._claimed_without_flag(
            session, "Are you ready to explore whether this is serving you?"
        )
        with patch("api.utils.extraction.check_done_when") as checker:
            on_model_turn(session, message, response)
        checker.assert_not_called()
        message.refresh_from_db()
        decision = message.usage["step_decision"]
        self.assertFalse(decision["model"]["asks_readiness"])
        self.assertFalse(decision["inferred_asks_readiness"])

    def test_yes_after_ready_to_continue_completes_the_step(self):
        session = self._two_steps()
        self._ask(
            session,
            "Now that you have that tool ready, are you ready to continue?",
        )
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="yes")
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={
                    "value": "not good enough before a presentation",
                    "confidence": 0.4,
                },
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
            patch("api.utils.Agent.get_response") as chat,
        ):
            outcome = confirm_readiness_reply(user_message)
        chat.assert_not_called()
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertTrue(step.completed)
        self.assertEqual(step.completion_result, "not good enough before a presentation")
        self.assertEqual(session.current_step_no, 2)
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

    def _greeting_prompt(self, prompts):
        def greeting(session, synthetic_text=None):
            sender = Participant.objects.filter(
                session=session, consumer__isnull=False
            ).first()
            synthetic = Message(
                session=session, sender=sender, text=synthetic_text or ""
            )
            prompts.append(user_prompt_with_hint(session, synthetic))
            return None

        return greeting

    def test_typed_yes_drops_the_previous_steps_goal_hint(self):
        session = self._two_steps()
        hint = "Ask one question that would supply what is still missing: the location"
        session.cached_prompt_meta = {
            "goal_hint": hint,
            "depth_hint_step_id": "ssnstp_old",
        }
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        self._ask(session, "Are you ready to continue?")
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="yes")
        prompts = []
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "the worry", "confidence": 0.8},
            ),
            patch(
                "api.utils.AIWorkerClient.request_session_greeting",
                side_effect=self._greeting_prompt(prompts),
            ),
        ):
            outcome = confirm_readiness_reply(user_message)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        self.assertEqual(session.current_step_no, 2)
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})
        self.assertNotIn("depth_hint_step_id", session.cached_prompt_meta or {})
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("<TURN_HINT>", prompts[0])
        self.assertNotIn("the location", prompts[0])

    def test_goal_hint_is_still_consumed_inside_the_same_step(self):
        session = self._session()
        hint = "Ask one question that would supply what is still missing: the situation"
        session.cached_prompt_meta = {"goal_hint": hint}
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="ok")
        prompted = user_prompt_with_hint(session, user_message)
        self.assertIn("<TURN_HINT>", prompted)
        self.assertIn("the situation", prompted)
        session.refresh_from_db()
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})
        self.assertEqual(session.current_step_no, 1)

    def test_ready_chip_drops_the_previous_steps_goal_hint(self):
        session = self._two_steps()
        hint = "Ask one question that would supply what is still missing: the plan"
        session.cached_prompt_meta = {"goal_hint": hint}
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        Message.objects.create(
            session=session,
            sender=agent,
            text="Are you ready to continue?",
            suggested_responses=[Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
            suggested_responses_kind=Constants.SUGGESTED_RESPONSES_KIND_READY,
        )
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(
            session=session, sender=user, text=Constants.CHIP_READY_YES
        )
        prompts = []
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "the worry", "confidence": 0.8},
            ),
            patch(
                "api.utils.AIWorkerClient.request_session_greeting",
                side_effect=self._greeting_prompt(prompts),
            ),
        ):
            outcome = consume_chip(user_message, True)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        self.assertEqual(session.current_step_no, 2)
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("<TURN_HINT>", prompts[0])
        self.assertNotIn("the plan", prompts[0])

    def test_yes_completes_when_the_completion_prompt_fails(self):
        session = self._two_steps()
        self._ask(session, "Are you ready to continue?")
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="Yes")
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                side_effect=RuntimeError("down"),
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
        ):
            outcome = confirm_readiness_reply(user_message)
        self.assertIsNotNone(outcome)
        session.refresh_from_db()
        step = session.session_steps.get(order=0)
        self.assertTrue(step.completed)
        self.assertFalse(step.completion_result)

    def test_longer_reply_after_ready_to_continue_stays_in_chat(self):
        session = self._two_steps()
        self._ask(session, "Are you ready to continue?")
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="yes, but I want to add something",
        )
        outcome = confirm_readiness_reply(user_message)
        self.assertIsNone(outcome)
        session.refresh_from_db()
        self.assertFalse(session.session_steps.get(order=0).completed)
        self.assertEqual(session.current_step_no, 1)

    def test_yes_after_ready_to_proceed_stays_in_chat(self):
        session = self._two_steps()
        self._ask(session, "Are you ready to proceed?")
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="yes")
        outcome = confirm_readiness_reply(user_message)
        self.assertIsNone(outcome)
        session.refresh_from_db()
        self.assertFalse(session.session_steps.get(order=0).completed)

    def test_yes_during_pre_exercise_does_not_complete(self):
        session = self._two_steps()
        session.current_step_no = 0
        session.save(update_fields=["current_step_no", "updated_at"])
        self._ask(session, "Are you ready to continue?")
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(session=session, sender=user, text="yes")
        outcome = confirm_readiness_reply(user_message)
        self.assertIsNone(outcome)
        session.refresh_from_db()
        self.assertFalse(session.session_steps.get(order=0).completed)
        self.assertEqual(session.current_step_no, 0)

    def test_posted_yes_does_not_call_the_model(self):
        session = self._two_steps()
        self._ask(
            session,
            "Now that you have that tool ready, are you ready to continue?",
        )
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "the presentation", "confidence": 0.8},
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
            patch("api.message.views.request_agent_response") as chat,
            patch("api.message.views.enqueue_agent_response") as queued,
        ):
            response = self._post(
                "/messages",
                {"session": session.id, "text": "yes"},
                self.consumer_one_access_token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        chat.assert_not_called()
        queued.assert_not_called()
        self.assertEqual(response.json["session_state"]["current_step_no"], 2)
        self.assertEqual(response.json["session_state"]["phase"], "step_active")
        session.refresh_from_db()
        self.assertTrue(session.session_steps.get(order=0).completed)
        self.assertEqual(
            session.session_steps.get(order=0).completion_result,
            "the presentation",
        )


class SummaryConfirmationTests(SimpleTestCase):
    def test_a_recap_counts_and_a_readiness_close_does_not(self):
        recap = (
            "So, to recap, you worry about missing deadlines and losing your job, "
            "and it comes up at night. Did I capture that accurately?"
        )
        close = (
            "The thought 'I'm going to miss a deadline and lose my job' feels less strong. "
            "We've reached the end of this step. Are you ready to continue?"
        )
        self.assertTrue(is_summary_confirmation(recap))
        self.assertFalse(is_summary_confirmation(close))
        self.assertFalse(is_summary_confirmation("Did I get that right?"))

    def test_rule_is_added_only_when_the_step_requires_a_confirmed_summary(self):
        required = "The user confirmed the summary is accurate."
        agreed = "The user has agreed with the summary of their decisions and alternative action."
        plain = "The user has named the worry and the situation."
        ready = "Ask if the user is ready to move on, and move on when the user agrees."
        rule = summary_confirmation_rule(required)
        self.assertIn("summarise what this step asked for", rule)
        self.assertNotIn("worry", rule)
        self.assertIn("summarise what this step asked for", summary_confirmation_rule(agreed))
        self.assertEqual(summary_confirmation_rule(plain), "")
        self.assertEqual(summary_confirmation_rule(ready), "")
