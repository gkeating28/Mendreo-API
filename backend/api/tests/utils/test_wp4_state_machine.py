from unittest.mock import patch

from django.test import override_settings
from rest_framework import status

from ...exercise.models import Exercise
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse, _state_machine_progression
from ...utils.SessionStateMachine import opening_turn
from ..exercise.test_pre_exercise import _pre_exercise_payload
from ..utils.BaseTest import BaseTest
from ..utils.manager import General


def _canned_greeting(session, synthetic_text=None):
    agent = Participant.objects.filter(session=session, agent__isnull=False).first()
    text = synthetic_text or "Hello"
    return Message.objects.create(
        session=session,
        sender=agent,
        text=text,
        is_step_complete=False,
        step_no=session.current_step_no,
        suggested_responses=[],
        question_kind=Constants.QUESTION_KIND_NONE,
    )


def _model_reply(**overrides):
    payload = {
        "text": "Tell me a bit more.",
        "reasoning": "test",
        "suggested_responses": ["Something else"],
        "step_goal_met": False,
        "asks_readiness": False,
        "question_kind": Constants.QUESTION_KIND_NONE,
        "risk_level": Constants.LIVE_RISK_LEVEL_NONE,
    }
    payload.update(overrides)
    response = ExerciseStateResponse(**payload)
    return response, {}, None, None


@override_settings(AI_STATE_MACHINE_ENABLED=True, AI_ASYNC_MESSAGES=False)
class Wp4StateMachineTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def test_progression_block_is_swapped_only_by_the_helper(self):
        from pathlib import Path

        raw = Path(
            Path(__file__).resolve().parents[2]
            / "utils"
            / "files"
            / "exercise_prompt.txt"
        ).read_text()
        self.assertIn("GOOD_PROGRESSION_EXAMPLES", raw)
        swapped = _state_machine_progression(raw)
        self.assertIn("Set asks_readiness", swapped)
        self.assertNotIn("GOOD_PROGRESSION_EXAMPLES", swapped)
        self.assertIn("<EXERCISE>", swapped)
        self.assertIn("GOOD_PROGRESSION_EXAMPLES", raw)

    def test_three_step_check_in_readiness_and_finish(self):
        exercise = General.create_exercise(data=_pre_exercise_payload())
        Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=3,
            total_steps_no=exercise.steps_no,
            subject="Done before",
        )
        script = [
            _model_reply(
                text="Are you ready for the next step?",
                step_goal_met=True,
                asks_readiness=True,
            ),
            _model_reply(
                text="Are you ready for the next step?",
                step_goal_met=True,
                asks_readiness=True,
            ),
            _model_reply(
                text="Are you ready for the next step?",
                step_goal_met=True,
                asks_readiness=True,
            ),
            _model_reply(
                text="Are you ready for the next step?",
                step_goal_met=True,
                asks_readiness=True,
            ),
            _model_reply(
                text="Are you ready to finish?",
                step_goal_met=True,
                asks_readiness=True,
            ),
        ]

        def fake_model(*args, **kwargs):
            return script.pop(0)

        with (
            patch(
                "api.utils.AIWorkerClient._run_session_greeting",
                side_effect=_canned_greeting,
            ),
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "a named thought", "confidence": 0.9},
            ) as extract,
            patch("api.utils.Agent.get_response", side_effect=fake_model) as chat,
        ):
            session = General.start_session(
                consumer=self.consumer_one, exercise=exercise
            )
            self.assertEqual(chat.call_count, 0)
            detail = self._get(session, self.consumer_one_access_token)
            state = detail.json["session_state"]
            self.assertEqual(state["phase"], Constants.SESSION_STATE_CHECK_IN)
            self.assertEqual(state["pending_action"], "start")
            self.assertEqual(state["current_step_no"], 0)
            self.assertEqual([step["status"] for step in state["steps"]], ["pending"] * 3)
            self.assertNotIn("completion_card", state)

            started = self._post(
                f"/sessions/{session.id}/start",
                {"summary": "Last time went better"},
                self.consumer_one_access_token,
            )
            self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
            self.assertEqual(chat.call_count, 0)
            self.assertEqual(started.json["current_step_no"], 1)
            self.assertEqual(started.json["phase"], "exercise")
            self.assertFalse(started.json["pre_exercise"]["pending"])
            self.assertEqual(started.json["session_state"]["phase"], "step_active")
            self.assertEqual(started.json["session_state"]["current_step_no"], 1)
            self.assertEqual(started.json["session_state"]["pending_action"], "none")
            self.assertEqual(started.json["messages"][0]["text"], opening_turn(1))
            self.assertFalse(started.json["messages"][0]["is_step_complete"])
            self.assertEqual(started.json["last_message"]["text"], opening_turn(1))

            ready = self._say(session, "I keep thinking I will fail.")
            self.assertEqual(chat.call_count, 1)
            self.assertEqual(ready.json["session_state"]["phase"], "awaiting_ready")
            self.assertEqual(ready.json["session_state"]["pending_action"], "ready")
            self.assertEqual(
                ready.json["suggested_responses"],
                [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET],
            )
            self.assertEqual(ready.json["suggested_responses_kind"], "ready")
            self.assertEqual(ready.json["question_kind"], "readiness")
            self.assertNotIn("completion_card", ready.json["session_state"])

            before = chat.call_count
            not_yet = self._say(
                session, Constants.CHIP_NOT_YET, from_suggested_response=True
            )
            self.assertEqual(chat.call_count, before)
            self.assertEqual(not_yet.json["session_state"]["phase"], "step_active")
            self.assertEqual(not_yet.json["session_state"]["pending_action"], "none")

            asked_again = self._say(session, "Still the same thought.")
            self.assertEqual(chat.call_count, 2)
            self.assertEqual(asked_again.json["session_state"]["phase"], "awaiting_ready")
            before = chat.call_count
            interruption = self._say(session, "I want to add one more detail.")
            self.assertEqual(chat.call_count, before)
            self.assertEqual(interruption.json["session_state"]["phase"], "step_active")

            self._say(session, "The thought is that I will fail the interview.")
            self.assertEqual(chat.call_count, 3)

            before = chat.call_count
            advanced = self._say(session, "Yes")
            self.assertEqual(chat.call_count, before)
            self.assertEqual(extract.call_count, 1)
            self.assertEqual(advanced.json["session_state"]["phase"], "step_active")
            self.assertEqual(advanced.json["session_state"]["current_step_no"], 2)
            self.assertEqual(
                [step["status"] for step in advanced.json["session_state"]["steps"]],
                ["completed", "active", "pending"],
            )
            self.assertEqual(
                advanced.json["session_state"]["completion_card"]["title"],
                "Well Done!",
            )
            self.assertEqual(advanced.json["text"], opening_turn(2))
            self.assertFalse(advanced.json["is_step_complete"])
            stamped = Message.objects.filter(
                session=session, is_step_complete=True
            ).order_by("-created_at").first()
            self.assertEqual(stamped.completion_result, "a named thought")
            self.assertEqual(stamped.step_no, 1)

            self._say(session, "It is a thinking trap.")
            before = chat.call_count
            confirmed = self._post(
                f"/sessions/{session.id}/ready",
                {"confirm": True},
                self.consumer_one_access_token,
            )
            self.assertEqual(confirmed.status_code, status.HTTP_200_OK, confirmed.json)
            self.assertEqual(chat.call_count, before)
            self.assertEqual(confirmed.json["session_state"]["current_step_no"], 3)
            self.assertEqual(confirmed.json["session_state"]["pending_action"], "none")
            self.assertIn("completion_card", confirmed.json["session_state"])
            self.assertEqual(confirmed.json["messages"][-1]["text"], opening_turn(3))

            self._say(session, "A fairer thought is that I can prepare.")
            self.assertEqual(
                Message.objects.filter(session=session, sender__agent__isnull=False)
                .order_by("-created_at")
                .first()
                .suggested_responses,
                [Constants.CHIP_FINISH, Constants.CHIP_NOT_YET],
            )
            before = chat.call_count
            finished = self._post(
                f"/sessions/{session.id}/finish",
                {},
                self.consumer_one_access_token,
            )
            self.assertEqual(finished.status_code, status.HTTP_200_OK, finished.json)
            self.assertEqual(chat.call_count, before)
            self.assertEqual(extract.call_count, 3)
            self.assertEqual(finished.json["session_state"]["phase"], "completed")
            self.assertEqual(finished.json["session_state"]["current_step_no"], 4)
            self.assertEqual(finished.json["session_state"]["pending_action"], "none")
            self.assertEqual(
                [step["status"] for step in finished.json["session_state"]["steps"]],
                ["completed", "completed", "completed"],
            )
            self.assertIn("completion_card", finished.json["session_state"])
            self.assertFalse(
                any(message["text"] == opening_turn(4) for message in finished.json["messages"])
            )

        session.refresh_from_db()
        self.assertTrue(session.completed)
        self.assertEqual(session.state, Constants.SESSION_STATE_COMPLETED)
        self.assertEqual(session.current_step_no, 4)
        exercise = Exercise.objects.get(id=exercise.id)
        self.assertEqual(exercise.completions_no, 1)
        self.assertEqual(script, [])

    def _say(self, session, text, from_suggested_response=False):
        body = {"session": session.id, "text": text}
        if from_suggested_response:
            body["from_suggested_response"] = True
        response = self._post("/messages", body, self.consumer_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        return response


class Wp4FlagOffTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def test_ready_and_finish_are_hidden_and_session_state_is_absent(self):
        exercise = General.create_exercise()
        with patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None):
            session = General.start_session(consumer=self.consumer_one, exercise=exercise)

        detail = self._get(session, self.consumer_one_access_token)
        self.assertNotIn("session_state", detail.json)
        self.assertEqual(session.state, Constants.SESSION_STATE_GENERAL)

        ready = self._post(
            f"/sessions/{session.id}/ready",
            {"confirm": True},
            self.consumer_one_access_token,
        )
        finish = self._post(
            f"/sessions/{session.id}/finish",
            {},
            self.consumer_one_access_token,
        )
        self.assertEqual(ready.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(finish.status_code, status.HTTP_404_NOT_FOUND)
