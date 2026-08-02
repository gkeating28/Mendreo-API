from datetime import timedelta
from unittest import mock

from django.utils import timezone
from rest_framework import status

from ..utils import Data
from ..utils.BaseTest import BaseTest
from ..utils.manager import General, Auth
from ...exercise.models import Exercise
from ...exercise.pre_exercise import (
    resolve_template,
    should_run_pre_exercise_checkin,
)
from ...knowledge.models import KnowledgeField
from ...knowledge.services import write_knowledge_entry
from ...session.models import Session
from ...utils import Constants


def _pre_exercise_payload(**overrides):
    data = Data.valid_exercise_flexible_thinking()
    data["steps"] = [
        {
            **step,
            "average_duration": step.get("average_duration", 300),
            "success_title": step.get("success_title", "Well Done!"),
        }
        for step in data["steps"]
    ]
    data.update(
        {
            "pre_exercise_enabled": True,
            "pre_exercise_description": "Warm check-in for returning users.",
            "pre_exercise_instruction": (
                "Hi {{user.first_name}}, before we start {{exercise.title}}, "
                "ask how things have been since {{last_session.date}}. "
                "Last sleep note: {{knowledge.sleep_quality}}."
            ),
            "pre_exercise_goal": "User briefly shares how the last practice went.",
            "pre_exercise_completion_prompt": "Summarise how the last practice went.",
            "pre_exercise_start_button_label": "Let's begin",
        }
    )
    data.update(overrides)
    return data


class PreExerciseExerciseTests(BaseTest):
    def endpoint(self):
        return "exercises"

    def _results(self, response):
        if isinstance(response.json, dict) and "results" in response.json:
            return response.json["results"]
        return response.json

    def test_create_and_list_filter_pre_exercise(self):
        enabled = self._create(_pre_exercise_payload(), self.admin_one_access_token)
        self.assertEqual(enabled.status_code, status.HTTP_201_CREATED, enabled.json)
        self.assertTrue(enabled.json["pre_exercise_enabled"])
        self.assertEqual(enabled.json["pre_exercise_start_button_label"], "Let's begin")

        disabled = self._create(
            _pre_exercise_payload(
                title="No Check In",
                pre_exercise_enabled=False,
                pre_exercise_instruction="",
                pre_exercise_goal="",
            ),
            self.admin_one_access_token,
        )
        self.assertEqual(disabled.status_code, status.HTTP_201_CREATED, disabled.json)

        listed = self._list(
            self.admin_one_access_token,
            {"pre_exercise": "enabled", "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in self._results(listed)]
        self.assertIn(enabled.json["id"], ids)
        self.assertNotIn(disabled.json["id"], ids)

        listed_off = self._list(
            self.admin_one_access_token,
            {"pre_exercise": "disabled", "paginated": "false"},
        )
        off_ids = [row["id"] for row in self._results(listed_off)]
        self.assertIn(disabled.json["id"], off_ids)

    def test_publish_requires_instruction_and_goal_when_enabled(self):
        response = self._create(
            _pre_exercise_payload(
                pre_exercise_instruction="",
                pre_exercise_goal="",
            ),
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pre_exercise_instruction", response.json)
        self.assertIn("pre_exercise_goal", response.json)

    def test_draft_can_omit_instruction_when_enabled(self):
        response = self._create(
            _pre_exercise_payload(
                status=Constants.EXERCISE_STATUS_DRAFT,
                pre_exercise_instruction="",
                pre_exercise_goal="",
            ),
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)

    def test_duplicate_copies_pre_exercise_fields(self):
        original = General.create_exercise(data=_pre_exercise_payload())
        response = self._post(
            "/exercises/duplicate",
            {"exercise": original.id, "name": "Copy With Check In"},
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        copy = Exercise.objects.get(id=response.json["id"])
        self.assertTrue(copy.pre_exercise_enabled)
        self.assertEqual(copy.pre_exercise_goal, original.pre_exercise_goal)
        self.assertEqual(copy.pre_exercise_start_button_label, "Let's begin")

    def test_test_pre_exercise_prompt_resolves_tokens(self):
        exercise = General.create_exercise(data=_pre_exercise_payload())
        field = KnowledgeField.objects.create(
            key="sleep_quality",
            label="Sleep",
            category="Wellbeing",
        )
        write_knowledge_entry(
            consumer=self.consumer_one,
            field=field,
            value="restless",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
            created_by=self.admin_one.user,
        )

        # Seed a prior completed session so last_session tokens resolve.
        prior = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=3,
            total_steps_no=3,
            subject="Prior practice",
        )
        Session.objects.filter(id=prior.id).update(
            created_at=timezone.now() - timedelta(days=3)
        )

        with mock.patch("api.utils.AI.AI.ask") as ask:
            ask.return_value = {"text": "How did last week go?"}
            response = self._post(
                f"/exercises/{exercise.id}/test-pre-exercise-prompt",
                {
                    "consumer_id": self.consumer_one.user_id,
                    "run_dry_run": True,
                },
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        instruction = response.json["resolved"]["instruction"]
        self.assertIn(self.consumer_one.user.first_name, instruction)
        self.assertIn("Flexible Thinking", instruction)
        self.assertIn("restless", instruction)
        self.assertEqual(response.json["dry_run"]["opening_message"], "How did last week go?")
        ask.assert_called_once()


class PreExerciseSessionTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def _enable_exercise(self):
        exercise = General.create_exercise(data=_pre_exercise_payload())
        return exercise

    def _complete_prior_session(self, consumer, exercise):
        session = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            completed=True,
            current_step_no=3,
            total_steps_no=exercise.steps_no,
            subject="Done before",
        )
        return session

    @mock.patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None)
    def test_first_run_skips_checkin(self, _greeting):
        exercise = self._enable_exercise()
        session = General.start_session(consumer=self.consumer_one, exercise=exercise)
        self.assertEqual(session.current_step_no, 1)
        self.assertFalse(session.in_pre_exercise_phase())
        self.assertFalse(should_run_pre_exercise_checkin(self.consumer_one, exercise))

    @mock.patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None)
    def test_every_repeat_starts_checkin_including_same_day(self, _greeting):
        exercise = self._enable_exercise()
        self._complete_prior_session(self.consumer_one, exercise)

        first_repeat = General.start_session(consumer=self.consumer_one, exercise=exercise)
        self.assertEqual(first_repeat.current_step_no, 0)
        self.assertTrue(first_repeat.in_pre_exercise_phase())

        detail = self._get(first_repeat, self.consumer_one_access_token)
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.json["phase"], "pre_exercise")
        self.assertTrue(detail.json["pre_exercise"]["pending"])
        self.assertEqual(detail.json["pre_exercise"]["start_button_label"], "Let's begin")

        # Complete check-in → Step 1
        handoff = self._post(
            f"/sessions/{first_repeat.id}/complete-pre-exercise",
            {"summary": "Felt better than last time"},
            self.consumer_one_access_token,
        )
        self.assertEqual(handoff.status_code, status.HTTP_200_OK, handoff.json)
        self.assertEqual(handoff.json["phase"], "exercise")
        self.assertTrue(handoff.json["pre_exercise"]["occurred"])
        self.assertEqual(
            handoff.json["pre_exercise"]["summary"], "Felt better than last time"
        )
        self.assertIsNotNone(handoff.json["pre_exercise"]["completed_at"])
        self.assertEqual(handoff.json["current_step_no"], 1)

        first_repeat.refresh_from_db()
        first_repeat.completed = True
        first_repeat.save(update_fields=["completed"])

        # Same-day second run still gets check-in (every-repeat cadence).
        second_repeat = General.start_session(
            consumer=self.consumer_one, exercise=exercise
        )
        self.assertNotEqual(second_repeat.id, first_repeat.id)
        self.assertEqual(second_repeat.current_step_no, 0)
        self.assertTrue(second_repeat.in_pre_exercise_phase())

    @mock.patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None)
    def test_resume_incomplete_same_day_does_not_recreate(self, _greeting):
        exercise = self._enable_exercise()
        self._complete_prior_session(self.consumer_one, exercise)

        first = General.start_session(consumer=self.consumer_one, exercise=exercise)
        resumed = General.start_session(consumer=self.consumer_one, exercise=exercise)
        self.assertEqual(first.id, resumed.id)
        self.assertEqual(resumed.current_step_no, 0)

    def test_resolve_template_unknown_token_empty(self):
        resolved = resolve_template(
            "Hello {{user.first_name}} {{missing.token}}",
            {"user.first_name": "Ada"},
        )
        self.assertEqual(resolved, "Hello Ada ")
