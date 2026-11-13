from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.Agent import (
    ExerciseStateResponse,
    _QUESTION_HINT,
    _READY_QUESTION,
    _STRAY_READY_HINT,
    _apply_readiness_guard,
    _apply_statement_guard,
    _clear_ready_claim,
    _last_sentence,
    _official_ready_question,
    _readiness_guard_applies,
    _readiness_question,
    _retry_once_with_steer,
    _risk_blocks_reply_guard,
    _statement_reply_stands,
    get_response,
)
from ..utils.BaseTest import BaseTest
from ..utils.manager import General

_EXPLORE = "Are you ready to explore how you might interact with these thoughts differently?"
_NEXT = "What would you do at that moment?"
_RECAP = (
    "You chose to step outside when the worry starts, and to leave your phone "
    "in the other room."
)
_RECAP_RETRY = "You chose to step outside when the worry starts. Do I have that right?"
_SORRY = "Sorry, I had an issue understanding your message"


class ReplyGuardImportTests(SimpleTestCase):
    def test_touched_names_import_without_patches(self):
        names = (
            get_response,
            _last_sentence,
            _READY_QUESTION,
            _readiness_question,
            _official_ready_question,
            _readiness_guard_applies,
            _clear_ready_claim,
            _risk_blocks_reply_guard,
            _STRAY_READY_HINT,
            _QUESTION_HINT,
            _retry_once_with_steer,
            _statement_reply_stands,
            _apply_readiness_guard,
            _apply_statement_guard,
        )
        for name in names:
            self.assertTrue(callable(name) or name is _READY_QUESTION or isinstance(name, str))


class ReplyGuardTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def _session(self, done_when="The user has named the worry."):
        exercise = General.create_exercise()
        exercise.steps.all().delete()
        exercise.steps_no = 2
        exercise.save(update_fields=["steps_no", "updated_at"])
        for order in range(2):
            Step.objects.create(
                exercise=exercise,
                title=f"Step {order + 1}",
                description="Describe it",
                instructions="Ask what the worry is.",
                completion_label="Named",
                done_when=done_when,
                order=order,
            )
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=1,
            total_steps_no=2,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        SessionStep.create(session, exercise)
        Participant.create_participants(session)
        return session

    def _ask(self, session, replies, *, claim=False, risk="none"):
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        calls = []

        class _FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, func=None, **kwargs):
                if func is None:
                    return lambda fn: fn
                return func

            def run_sync(self, user_prompt="", **kwargs):
                calls.append(user_prompt)
                if replies[min(len(calls) - 1, len(replies) - 1)] is None:
                    raise RuntimeError("retry failed")
                text = replies[min(len(calls) - 1, len(replies) - 1)]
                output = ExerciseStateResponse(
                    text=text,
                    reasoning="test",
                    suggested_responses=[],
                    step_goal_met=claim,
                    asks_readiness=claim,
                    risk_level=risk,
                )
                return SimpleNamespace(
                    output=output,
                    usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
                )

        with (
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", _FakeAgent),
        ):
            response, _, _, _ = get_response(session, user_message)
        return calls, response

    def test_a_stray_readiness_question_on_an_unfinished_step_is_retried(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "what they would do"},
        ) as checked:
            calls, response = self._ask(session, [_EXPLORE, _NEXT])
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("Ask the step's next question", calls[1])
        self.assertNotIn("Ask the step's next question", calls[0])
        self.assertEqual(response.text, _NEXT)

    def test_the_same_question_on_a_finished_step_is_kept(self):
        session = self._session()
        row = session.session_steps.get(order=0)
        row.goal_met_at = timezone.now()
        row.save(update_fields=["goal_met_at", "updated_at"])
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=AssertionError("finished step must not be checked"),
        ):
            calls, response = self._ask(session, [_EXPLORE], claim=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, _EXPLORE)
        self.assertTrue(response.step_goal_met)
        self.assertTrue(response.asks_readiness)

    def test_a_statement_recap_retries_and_ends_with_the_exact_closing_sentence(self):
        session = self._session(done_when="The user confirmed the summary is accurate.")
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=AssertionError("a statement is not a readiness check"),
        ):
            calls, response = self._ask(session, [_RECAP, _RECAP_RETRY])
        self.assertEqual(len(calls), 2)
        self.assertIn('exactly "Do I have that right?"', calls[1])
        self.assertNotIn('exactly "Do I have that right?"', calls[0])
        self.assertTrue(response.text.endswith("Do I have that right?"))

    def test_a_high_risk_turn_is_not_retried(self):
        session = self._session()
        session.live_risk_level = Constants.LIVE_RISK_LEVEL_HIGH
        session.save(update_fields=["live_risk_level", "updated_at"])
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=AssertionError("high risk must not be checked"),
        ):
            calls, response = self._ask(session, [_EXPLORE, _NEXT], claim=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, _EXPLORE)

    def test_general_chat_is_not_retried(self):
        session = Session.objects.create(consumer=self.consumer_one)
        Participant.create_participants(session)
        calls, response = self._ask(session, ["You have a plan to walk when it happens."])
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, "You have a plan to walk when it happens.")

    def test_a_retry_that_throws_keeps_the_original(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the plan"},
        ):
            calls, response = self._ask(session, [_EXPLORE, None])
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(response.text, _EXPLORE)
        self.assertNotIn(_SORRY, response.text)

    def test_a_checker_bug_keeps_the_original_and_is_not_the_sorry_reply(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=RuntimeError("checker broke"),
        ):
            calls, response = self._ask(session, [_EXPLORE, _NEXT])
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, _EXPLORE)
        self.assertNotIn(_SORRY, response.text)

    def test_a_retry_that_is_still_a_readiness_question_is_kept_with_the_claim_cleared(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the plan"},
        ) as checked:
            calls, response = self._ask(
                session,
                [_EXPLORE, _EXPLORE, _EXPLORE],
                claim=True,
            )
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.text, _EXPLORE)
        self.assertFalse(response.step_goal_met)
        self.assertFalse(response.asks_readiness)

    def test_an_official_ready_question_without_a_claim_is_not_retried(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=AssertionError("an unclaimed official question is not checked here"),
        ):
            calls, response = self._ask(session, ["Are you ready for the next step?"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, "Are you ready for the next step?")
