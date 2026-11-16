from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.turn_hint import LAST_STEP_HINT
from ...utils.Agent import (
    STEP_REFERENCE_RULES,
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

    def test_shared_rules_do_not_name_one_exercise(self):
        for text in (STEP_REFERENCE_RULES, LAST_STEP_HINT):
            self.assertNotIn("alternative action", text)
            self.assertNotIn("the worry", text)
            self.assertNotIn("those situations", text)
        self.assertIn("using the user's own terms", STEP_REFERENCE_RULES)
        self.assertIn("or the step's instructions tell you to suggest one", STEP_REFERENCE_RULES)
        self.assertIn("working through several prompts", STEP_REFERENCE_RULES)
        self.assertIn("done_when ask for one", STEP_REFERENCE_RULES)
        self.assertIn('the exact sentence "Do I have that right?"', STEP_REFERENCE_RULES)
        self.assertIn("what this step's instructions told you to recap", LAST_STEP_HINT)
        self.assertIn('exactly "Do I have that right?"', LAST_STEP_HINT)


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

    def _two_providers(self, reply):
        providers = (
            SimpleNamespace(default_model="a", _resolved_model_name="a"),
            SimpleNamespace(default_model="b", _resolved_model_name="b"),
        )

        class _FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def tool(self, func=None, **kwargs):
                if func is None:
                    return lambda fn: fn
                return func

            def run_sync(self, user_prompt="", **kwargs):
                return reply(user_prompt, **kwargs)

        def failover(operation):
            last = None
            for provider in providers:
                try:
                    return operation(provider), provider
                except Exception as exc:
                    last = exc
            raise last

        return _FakeAgent, failover

    def test_one_hint_build_survives_failover_and_both_guard_retries(self):
        from api.utils.turn_hint import step_progress_hint as real_hint

        session = self._session()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        for _ in range(5):
            Message.objects.create(
                session=session,
                sender=user,
                text="I keep thinking about the deadline.",
            )
        counts = {"hint": 0, "check": 0}
        calls = []
        answers = [
            _EXPLORE,
            "You chose to step outside when the worry starts.",
            _NEXT,
        ]

        def counting_hint(session, message):
            counts["hint"] += 1
            return real_hint(session, message)

        def counting_check(session, step):
            counts["check"] += 1
            return {"met": False, "missing": "what they would do next"}

        def run_sync(user_prompt="", **kwargs):
            calls.append(user_prompt)
            if len(calls) % 2 == 1:
                raise RuntimeError("provider down")
            text = answers[(len(calls) // 2) - 1]
            output = ExerciseStateResponse(
                text=text,
                reasoning="test",
                suggested_responses=[],
                step_goal_met=False,
                asks_readiness=False,
                risk_level="none",
            )
            return SimpleNamespace(
                output=output,
                usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
            )

        fake, failover = self._two_providers(run_sync)
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        with (
            patch("api.utils.turn_hint.step_progress_hint", counting_hint),
            patch("api.utils.extraction.check_done_when", counting_check),
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            response, _, _, _ = get_response(session, user_message)

        self.assertEqual(counts["hint"], 1)
        self.assertEqual(counts["check"], 1)
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[0], calls[1])
        self.assertNotIn("Ask the step's next question", calls[0])
        self.assertTrue(calls[2].startswith(calls[0]))
        self.assertTrue(calls[3].startswith(calls[0]))
        self.assertIn("Ask the step's next question", calls[2])
        self.assertIn("Ask the step's next question", calls[3])
        self.assertIn("exactly one question", calls[4])
        self.assertIn("exactly one question", calls[5])
        self.assertEqual(response.text, _NEXT)
        session.refresh_from_db()
        self.assertEqual(session.cached_prompt_meta["done_when_rejections"]["1"], 1)
        self.assertFalse(hasattr(session, "_turn_done_when_result"))

    def test_a_stored_goal_hint_is_on_every_attempt(self):
        from api.utils.turn_hint import step_progress_hint as real_hint

        session = self._session()
        goal = "Ask one question about the bus they named."
        session.cached_prompt_meta = {"goal_hint": goal}
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        counts = {"hint": 0}
        calls = []

        def counting_hint(session, message):
            counts["hint"] += 1
            return real_hint(session, message)

        def run_sync(user_prompt="", **kwargs):
            calls.append(user_prompt)
            if len(calls) % 2 == 1:
                raise RuntimeError("provider down")
            text = _EXPLORE if len(calls) == 2 else _NEXT
            output = ExerciseStateResponse(
                text=text,
                reasoning="test",
                suggested_responses=[],
                step_goal_met=False,
                asks_readiness=False,
                risk_level="none",
            )
            return SimpleNamespace(
                output=output,
                usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
            )

        fake, failover = self._two_providers(run_sync)
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        with (
            patch("api.utils.turn_hint.step_progress_hint", counting_hint),
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "the plan"},
            ) as checked,
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            get_response(session, user_message)

        self.assertEqual(counts["hint"], 0)
        self.assertEqual(checked.call_count, 1)
        self.assertGreaterEqual(len(calls), 4)
        for prompt in calls:
            self.assertIn(goal, prompt)
        self.assertNotIn("Ask the step's next question", calls[0])
        self.assertIn("Ask the step's next question", calls[2])
        session.refresh_from_db()
        self.assertNotIn("goal_hint", session.cached_prompt_meta or {})

    def test_a_failed_turn_does_not_keep_the_rejection(self):
        from api.utils.turn_hint import step_progress_hint as real_hint

        session = self._session()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        for _ in range(5):
            Message.objects.create(
                session=session,
                sender=user,
                text="I keep thinking about the deadline.",
            )
        counts = {"hint": 0, "check": 0}

        def counting_hint(session, message):
            counts["hint"] += 1
            return real_hint(session, message)

        def counting_check(session, step):
            counts["check"] += 1
            return {"met": False, "missing": "what they would do next"}

        def run_sync(user_prompt="", **kwargs):
            raise RuntimeError("provider down")

        fake, failover = self._two_providers(run_sync)
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        with (
            patch("api.utils.turn_hint.step_progress_hint", counting_hint),
            patch("api.utils.extraction.check_done_when", counting_check),
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            response, _, _, _ = get_response(session, user_message)

        self.assertEqual(counts["hint"], 1)
        self.assertEqual(counts["check"], 1)
        self.assertIn(_SORRY, response.text)
        session.refresh_from_db()
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})

    def test_general_chat_builds_the_hint_once_across_providers(self):
        from api.utils.turn_hint import step_progress_hint as real_hint

        session = Session.objects.create(consumer=self.consumer_one)
        user, _agent = Participant.create_participants(session)
        counts = {"hint": 0}
        calls = []

        def counting_hint(session, message):
            counts["hint"] += 1
            return real_hint(session, message)

        def run_sync(user_prompt="", **kwargs):
            calls.append(user_prompt)
            if len(calls) == 1:
                raise RuntimeError("provider down")
            output = ExerciseStateResponse(
                text="You have a plan to walk when it happens.",
                reasoning="test",
                suggested_responses=[],
                step_goal_met=False,
                asks_readiness=False,
                risk_level="none",
            )
            return SimpleNamespace(
                output=output,
                usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
            )

        fake, failover = self._two_providers(run_sync)
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="I might walk when it happens.",
        )
        with (
            patch("api.utils.turn_hint.step_progress_hint", counting_hint),
            patch(
                "api.utils.extraction.check_done_when",
                side_effect=AssertionError("general chat must not check done_when"),
            ),
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            response, _, _, _ = get_response(session, user_message)

        self.assertEqual(counts["hint"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(response.text, "You have a plan to walk when it happens.")
        session.refresh_from_db()
        self.assertNotIn("done_when_rejections", session.cached_prompt_meta or {})

    def test_turn_done_when_result_is_cleared_on_every_path(self):
        session = self._session()
        session._turn_done_when_result = {"met": True, "missing": ""}
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the plan"},
        ) as checked:
            calls, response = self._ask(session, [_EXPLORE, _NEXT])
        self.assertEqual(checked.call_count, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response.text, _NEXT)
        self.assertFalse(hasattr(session, "_turn_done_when_result"))

        session = self._session()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        for _ in range(5):
            Message.objects.create(
                session=session,
                sender=user,
                text="I keep thinking about the deadline.",
            )
        session._turn_done_when_result = {"met": True, "missing": "stale"}

        def run_sync(user_prompt="", **kwargs):
            raise RuntimeError("provider down")

        fake, failover = self._two_providers(run_sync)
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        with (
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "what they would do next"},
            ),
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            response, _, _, _ = get_response(session, user_message)
        self.assertIn(_SORRY, response.text)
        self.assertFalse(hasattr(session, "_turn_done_when_result"))

        session = self._session()
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        for _ in range(5):
            Message.objects.create(
                session=session,
                sender=user,
                text="I keep thinking about the deadline.",
            )
        session._turn_done_when_result = {"met": True, "missing": "stale"}

        def succeed(user_prompt="", **kwargs):
            output = ExerciseStateResponse(
                text="You have a plan.",
                reasoning="test",
                suggested_responses=[],
                step_goal_met=False,
                asks_readiness=False,
                risk_level="none",
            )
            return SimpleNamespace(
                output=output,
                usage=lambda: SimpleNamespace(input_tokens=1, output_tokens=1),
            )

        fake, failover = self._two_providers(succeed)
        user_message = Message.objects.create(
            session=session,
            sender=user,
            text="The worry is the deadline.",
        )
        with (
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "what they would do next"},
            ),
            patch("api.utils.Agent.normalise_reply", side_effect=RuntimeError("after the reply")),
            patch("api.utils.Agent.build_pydantic_model", return_value=(object(), None)),
            patch("api.utils.Agent.Agent", fake),
            patch("api.utils.Agent.run_with_failover", failover),
        ):
            with self.assertRaises(RuntimeError):
                get_response(session, user_message)
        self.assertFalse(hasattr(session, "_turn_done_when_result"))

    def test_an_official_ready_question_without_a_claim_is_not_retried(self):
        session = self._session()
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=AssertionError("an unclaimed official question is not checked here"),
        ):
            calls, response = self._ask(session, ["Are you ready for the next step?"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(response.text, "Are you ready for the next step?")
