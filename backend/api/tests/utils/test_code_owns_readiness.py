"""Code-owned readiness question. Flag off keeps today's replies."""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils import Constants
from ...utils.Agent import (
    STEP_SCOPE_RULES,
    ExerciseStateResponse,
    _get_formatted_exercise_steps_text,
    _PROGRESSION_START,
    _prepare_prompt,
    _state_machine_progression,
    step_scope_rules,
)
from ...utils.SessionStateMachine import (
    CODE_READY_FINISH,
    CODE_READY_NEXT_STEP,
    _STRIPPED_READINESS_FALLBACK,
    code_owns_readiness,
    confirm_readiness_reply,
    handle_typed_while_awaiting,
    on_model_turn,
    readiness_path,
)
from ...utils.turn_hint import (
    LAST_STEP_HINT,
    NOT_THE_LAST_STEP_HINT,
    last_step_hint,
    not_the_last_step_hint,
)
from ..utils.BaseTest import BaseTest
from ..utils.manager import General


def _response(text, *, goal=True, asks=True):
    return ExerciseStateResponse(
        text=text,
        reasoning="test",
        suggested_responses=[],
        step_goal_met=goal,
        asks_readiness=asks,
        question_kind=Constants.QUESTION_KIND_READINESS if asks else Constants.QUESTION_KIND_OPEN,
    )


class CodeOwnsReadinessTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def _exercise(self, *, steps=1, done_when="The user has named the worry and the situation."):
        exercise = General.create_exercise()
        exercise.steps.all().delete()
        exercise.steps_no = steps
        exercise.depth_check = False
        exercise.save(update_fields=["steps_no", "depth_check", "updated_at"])
        for order in range(steps):
            Step.objects.create(
                exercise=exercise,
                title=f"Step {order + 1}",
                description="Describe it",
                instructions="Ask what the worry is.",
                completion_label="Named",
                completion_prompt="Summarise the worry.",
                done_when=done_when,
                order=order,
            )
        return exercise

    def _session(self, exercise, *, step_no=1, done_when=None):
        total = exercise.steps.count()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            current_step_no=step_no,
            total_steps_no=total,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        SessionStep.create(session, exercise)
        Participant.create_participants(session)
        if done_when is not None:
            live = session.session_steps.get(order=step_no - 1)
            live.step.done_when = done_when
            live.step.save(update_fields=["done_when", "updated_at"])
        return session

    def _agent(self, session, text, *, goal=True, asks=True):
        agent = Participant.objects.filter(session=session, agent__isnull=False).first()
        message = Message.objects.create(
            session=session,
            sender=agent,
            text=text,
            reasoning="test",
            question_kind=(
                Constants.QUESTION_KIND_READINESS if asks else Constants.QUESTION_KIND_OPEN
            ),
            suggested_responses=[],
        )
        return message, _response(text, goal=goal, asks=asks)

    def _user(self, session, text):
        user = Participant.objects.filter(session=session, consumer__isnull=False).first()
        return Message.objects.create(session=session, sender=user, text=text)

    def _summary(self, question):
        return (
            "So, to recap, you worry about missing deadlines and losing your job, "
            "and it comes up at night. " + question
        )

    def test_flag_off_leaves_the_model_question_and_records_the_model_path(self):
        session = self._session(self._exercise(steps=2))
        kept = "The worry is the deadline. Are you ready for the summary?"
        message, response = self._agent(session, kept)
        with (
            self.assertLogs("api.utils.SessionStateMachine", level="INFO") as logs,
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "the situation"},
            ),
        ):
            on_model_turn(session, message, response)
        message.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(message.text, kept)
        self.assertEqual(message.suggested_responses, [])
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)
        decision = message.usage["step_decision"]
        self.assertEqual(decision["readiness_owner"], "model")
        self.assertEqual(decision["readiness_reason"], "off")
        self.assertEqual(decision["readiness_action"], "left")
        self.assertTrue(
            any(
                "readiness_path" in line
                and f"exercise_id={session.exercise_id}" in line
                and "owner=model" in line
                and "reason=off" in line
                and "action=left" in line
                for line in logs.output
            )
        )

        passed = self._session(self._exercise(steps=2))
        original = "Are you ready to continue?"
        message, response = self._agent(passed, original)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(passed, message, response)
        message.refresh_from_db()
        passed.refresh_from_db()
        self.assertEqual(message.text, original)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )
        self.assertEqual(passed.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(message.usage["step_decision"]["readiness_action"], "left")

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True)
    def test_flag_on_appends_on_a_pass_and_strips_on_a_fail(self):
        session = self._session(self._exercise(steps=2))
        message, response = self._agent(
            session, "The worry is the deadline. Are you ready to continue?"
        )
        with (
            self.assertLogs("api.utils.SessionStateMachine", level="INFO") as logs,
            patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": True, "missing": ""},
            ),
        ):
            on_model_turn(session, message, response)
        message.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(
            message.text, f"The worry is the deadline. {CODE_READY_NEXT_STEP}"
        )
        self.assertEqual(message.text.count(CODE_READY_NEXT_STEP), 1)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        decision = message.usage["step_decision"]
        self.assertEqual(decision["readiness_owner"], "code")
        self.assertEqual(decision["readiness_reason"], "flag")
        self.assertEqual(decision["readiness_action"], "appended")
        self.assertTrue(any("owner=code" in line and "action=appended" in line for line in logs.output))

        for question in (
            "Are you ready for the summary?",
            "Are you ready for me to summarize?",
            "Are you ready for the next step?",
        ):
            failed = self._session(self._exercise(steps=2))
            text = f"The worry is the deadline. {question}"
            message, response = self._agent(failed, text)
            with patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "the situation"},
            ):
                on_model_turn(failed, message, response)
            message.refresh_from_db()
            failed.refresh_from_db()
            self.assertEqual(message.text, "The worry is the deadline.", question)
            self.assertEqual(message.suggested_responses, [])
            self.assertEqual(failed.state, Constants.SESSION_STATE_STEP_ACTIVE)
            self.assertIsNone(failed.session_steps.get(order=0).goal_met_at)
            self.assertEqual(message.usage["step_decision"]["readiness_action"], "stripped")

        already = self._session(self._exercise(steps=2))
        message, response = self._agent(
            already, f"The worry is the deadline. {CODE_READY_NEXT_STEP}"
        )
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(already, message, response)
        message.refresh_from_db()
        self.assertEqual(message.text.count(CODE_READY_NEXT_STEP), 1)

        only = self._session(self._exercise(steps=2))
        message, response = self._agent(only, "Are you ready for the summary?")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            on_model_turn(only, message, response)
        message.refresh_from_db()
        self.assertEqual(message.text, _STRIPPED_READINESS_FALLBACK)

        proceed = self._session(self._exercise(steps=2))
        kept = "Are you ready to proceed?"
        message, response = self._agent(proceed, kept, goal=True, asks=True)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            on_model_turn(proceed, message, response)
        message.refresh_from_db()
        self.assertEqual(message.text, kept)

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True)
    def test_last_step_uses_the_finish_sentence_and_chip(self):
        session = self._session(self._exercise(steps=1))
        message, response = self._agent(session, "That is the plan. Are you ready to finish?")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, message, response)
        message.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(message.text, f"That is the plan. {CODE_READY_FINISH}")
        self.assertNotIn(CODE_READY_NEXT_STEP, message.text)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_FINISH, Constants.CHIP_NOT_YET],
        )
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True)
    def test_summary_question_stays_until_the_summary_is_confirmed(self):
        done = "The user confirmed the summary is accurate."
        exercise = self._exercise(steps=1, done_when=done)
        session = self._session(exercise)
        question = self._summary("Does this plan sound right to you?")
        message, response = self._agent(session, question)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, message, response)
        message.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(message.text, question)
        self.assertNotIn("Are you ready", message.text)
        self.assertEqual(message.suggested_responses, [])
        self.assertEqual(session.state, Constants.SESSION_STATE_STEP_ACTIVE)

        self._user(session, "Yes, that covers it")
        follow, follow_response = self._agent(session, "Thank you for confirming that.")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(session, follow, follow_response)
        follow.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(
            follow.text, f"Thank you for confirming that. {CODE_READY_FINISH}"
        )
        self.assertNotIn(CODE_READY_NEXT_STEP, follow.text)
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True)
    def test_not_yet_restores_chips_without_appending(self):
        session = self._session(self._exercise(steps=2))
        session.state = Constants.SESSION_STATE_AWAITING_READY
        session.cached_prompt_meta = {"not_ready_keep_gate": True}
        session.save(update_fields=["state", "cached_prompt_meta", "updated_at"])
        text = "Take your time. We can stay with this."
        message, response = self._agent(session, text, goal=False, asks=False)
        on_model_turn(session, message, response)
        message.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(message.text, text)
        self.assertNotIn(CODE_READY_NEXT_STEP, message.text)
        self.assertEqual(
            message.suggested_responses,
            [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
        )
        self.assertEqual(session.state, Constants.SESSION_STATE_AWAITING_READY)
        self.assertNotIn("not_ready_keep_gate", session.cached_prompt_meta or {})

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True, AI_ASYNC_MESSAGES=False)
    def test_typed_yes_before_acceptance_reaches_the_model_and_after_it_does_not(self):
        failed = self._session(self._exercise(steps=2))
        message, response = self._agent(failed, "Are you ready for the summary?")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "the situation"},
        ):
            on_model_turn(failed, message, response)
        user_message = self._user(failed, "yes")
        self.assertIsNone(handle_typed_while_awaiting(user_message))
        self.assertIsNone(confirm_readiness_reply(user_message))
        with (
            patch(
                "api.message.views.request_agent_response",
                side_effect=lambda user_message, session: user_message,
            ) as chat,
            patch("api.message.views.enqueue_agent_response") as queued,
        ):
            response = self._post(
                "/messages",
                {"session": failed.id, "text": "yes"},
                self.consumer_one_access_token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        chat.assert_called_once()
        queued.assert_not_called()
        failed.refresh_from_db()
        self.assertEqual(failed.current_step_no, 1)
        self.assertEqual(failed.state, Constants.SESSION_STATE_STEP_ACTIVE)

        passed = self._session(self._exercise(steps=2))
        message, response = self._agent(passed, "The worry is the deadline.")
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ):
            on_model_turn(passed, message, response)
        passed.refresh_from_db()
        self.assertEqual(passed.state, Constants.SESSION_STATE_AWAITING_READY)
        with (
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "the worry", "confidence": 0.8},
            ),
            patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None),
            patch("api.message.views.request_agent_response") as chat,
            patch("api.message.views.enqueue_agent_response") as queued,
        ):
            response = self._post(
                "/messages",
                {"session": passed.id, "text": "yes"},
                self.consumer_one_access_token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        chat.assert_not_called()
        queued.assert_not_called()
        passed.refresh_from_db()
        self.assertEqual(passed.current_step_no, 2)
        self.assertTrue(passed.session_steps.get(order=0).completed)
        self.assertFalse(passed.session_steps.get(order=1).completed)

    def test_allow_list_selects_one_exercise(self):
        chosen = self._exercise(steps=2)
        other = self._exercise(steps=2)
        chosen_session = self._session(chosen)
        other_session = self._session(other)
        with override_settings(
            EXERCISE_CODE_OWNS_READINESS=False,
            EXERCISE_CODE_OWNS_READINESS_EXERCISE_IDS=f" {chosen.id} , not-an-id ",
        ):
            self.assertTrue(code_owns_readiness(chosen_session))
            self.assertFalse(code_owns_readiness(other_session))
            self.assertEqual(readiness_path(chosen_session), ("code", "allow_list"))
            kept = "The worry is the deadline. Are you ready for the summary?"
            chosen_message, chosen_response = self._agent(chosen_session, kept)
            other_message, other_response = self._agent(other_session, kept)
            with patch(
                "api.utils.extraction.check_done_when",
                return_value={"met": False, "missing": "the situation"},
            ):
                on_model_turn(chosen_session, chosen_message, chosen_response)
                on_model_turn(other_session, other_message, other_response)
        chosen_message.refresh_from_db()
        other_message.refresh_from_db()
        self.assertEqual(chosen_message.text, "The worry is the deadline.")
        self.assertEqual(chosen_message.usage["step_decision"]["readiness_reason"], "allow_list")
        self.assertEqual(chosen_message.usage["step_decision"]["readiness_action"], "stripped")
        self.assertEqual(other_message.text, kept)
        self.assertEqual(other_message.usage["step_decision"]["readiness_owner"], "model")
        self.assertEqual(other_message.usage["step_decision"]["readiness_reason"], "off")
        self.assertEqual(other_message.usage["step_decision"]["readiness_action"], "left")

    @override_settings(EXERCISE_CODE_OWNS_READINESS=True)
    def test_main_flag_ignores_the_allow_list(self):
        exercise = self._exercise(steps=1)
        session = self._session(exercise)
        with override_settings(EXERCISE_CODE_OWNS_READINESS_EXERCISE_IDS="00000000-0000-0000-0000-000000000000"):
            self.assertTrue(code_owns_readiness(session))
            from ...utils.SessionStateMachine import readiness_path

            self.assertEqual(readiness_path(session), ("code", "flag"))

    def test_prompt_cache_rebuilds_when_the_flag_flips(self):
        exercise = self._exercise(steps=2)
        session = self._session(exercise)
        off = _prepare_prompt(session)
        self.assertIn(
            "Only ask whether they are ready for the next step when every part of Done when is covered.",
            off,
        )
        self.assertIn("Set asks_readiness", off)
        self.assertEqual(_prepare_prompt(session), off)
        self.assertFalse(session.cached_prompt_meta.get("code_owns_readiness"))

        with override_settings(EXERCISE_CODE_OWNS_READINESS=True):
            on = _prepare_prompt(session)
            self.assertNotEqual(on, off)
            self.assertNotIn(
                "Only ask whether they are ready for the next step when every part", on
            )
            self.assertNotIn("you may ask whether they are ready for the next step", on)
            self.assertNotIn("Set asks_readiness", on)
            self.assertIn("Do not ask whether they are ready.", on)
            self.assertIn("The app asks that question.", on)
            self.assertIn("set step_goal_met", on)
            self.assertTrue(session.cached_prompt_meta.get("code_owns_readiness"))
            self.assertEqual(_prepare_prompt(session), on)

        with override_settings(EXERCISE_CODE_OWNS_READINESS=False):
            restored = _prepare_prompt(session)
        self.assertIn(
            "Only ask whether they are ready for the next step when every part of Done when is covered.",
            restored,
        )
        self.assertIn("Set asks_readiness", restored)
        self.assertFalse(session.cached_prompt_meta.get("code_owns_readiness"))

    def test_scope_and_hints_match_today_unless_the_flag_is_on(self):
        self.assertEqual(step_scope_rules(code_owns=False), STEP_SCOPE_RULES)
        owned = step_scope_rules(code_owns=True)
        self.assertNotIn("you may ask whether they are ready", owned)
        self.assertNotIn("Ask whether they are ready for the next step only once", owned)
        self.assertIn("set step_goal_met", owned)
        self.assertIn("If a part is not covered yet, continue with this step's instructions for it.", owned)

        bare = SimpleNamespace(exercise_id=None, consumer=None)
        self.assertEqual(not_the_last_step_hint(bare), NOT_THE_LAST_STEP_HINT)
        self.assertEqual(last_step_hint(bare), LAST_STEP_HINT.format(name="The user"))
        with override_settings(EXERCISE_CODE_OWNS_READINESS=True):
            self.assertNotIn("ask only whether they are ready", not_the_last_step_hint(bare))
            self.assertIn("set step_goal_met", not_the_last_step_hint(bare))
            self.assertNotIn("ask only whether they are ready to finish", last_step_hint(bare))
            self.assertIn("set step_goal_met", last_step_hint(bare))
            self.assertIn("ask if you have it right", last_step_hint(bare))

        raw = (
            _PROGRESSION_START
            + "\nGOOD_PROGRESSION_EXAMPLES\n    </PROGRAMMING_INSTRUCTIONS>"
        )
        swapped = _state_machine_progression(raw)
        self.assertIn("Set asks_readiness", swapped)
        self.assertNotIn("GOOD_PROGRESSION_EXAMPLES", swapped)
        owned_swap = _state_machine_progression(raw, code_owns=True)
        self.assertNotIn("Set asks_readiness", owned_swap)
        self.assertIn("Set step_goal_met", owned_swap)

        exercise = self._exercise(steps=2)
        off = _get_formatted_exercise_steps_text(exercise, code_owns=False)
        on = _get_formatted_exercise_steps_text(exercise, code_owns=True)
        self.assertIn("asks_readiness", off)
        self.assertIn("whether they are ready for the next step.", off)
        self.assertIn("whether they are ready to finish.", off)
        self.assertNotIn("Do not ask whether they are ready", off)
        self.assertIn("Do not ask whether they are ready for the next step.", on)
        self.assertNotIn("asks_readiness", on)
        source = inspect.getsource(_get_formatted_exercise_steps_text)
        self.assertIn('Are you ready to see your summary?', source)
        self.assertNotIn("Are you ready to see your summary?", off)
        self.assertNotIn("Are you ready to see your summary?", on)
