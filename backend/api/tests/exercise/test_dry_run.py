from types import SimpleNamespace
from unittest import mock

from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ...exercise_summary.models import ExerciseSummary
from ...message.models import Message
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...utils.Agent import _get_formatted_exercise_steps_text


class StepDryRunTests(BaseTest):
    def endpoint(self):
        return "exercises"

    def _exercise(self):
        return General.create_exercise()

    def test_unsaved_step_text_overrides_saved_copy(self):
        exercise = self._exercise()
        step = exercise.steps.order_by("order").first()
        saved_instructions = step.instructions
        marker = "UNSAVED-DRY-RUN-INSTRUCTION"

        with mock.patch("api.utils.AI.AI.ask") as ask:
            ask.return_value = {"text": "Opening from the unsaved step."}
            response = self._post(
                f"/exercises/{exercise.id}/steps/{step.id}/dry-run",
                {
                    "consumer_id": self.consumer_one.user_id,
                    "title": "Unsaved title",
                    "description": "Unsaved description",
                    "instructions": marker,
                    "reference_material": "Unsaved reference",
                    "done_when": "Unsaved done when",
                    "order": step.order,
                },
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertIn(marker, response.json["prompt"])
        self.assertEqual(response.json["opening_message"], "Opening from the unsaved step.")
        step.refresh_from_db()
        self.assertEqual(step.instructions, saved_instructions)
        self.assertNotIn(marker, step.instructions or "")

    def test_unsaved_step_without_id_is_not_stored(self):
        exercise = self._exercise()
        before = Step.objects.filter(exercise=exercise).count()
        marker = "UNSAVED-NEW-STEP"

        with mock.patch("api.utils.AI.AI.ask") as ask:
            ask.return_value = {"text": "Hello from a new step."}
            response = self._post(
                f"/exercises/{exercise.id}/dry-run",
                {
                    "consumer_id": self.consumer_one.user_id,
                    "title": "Brand new step",
                    "description": "Not saved",
                    "instructions": marker,
                    "reference_material": "",
                    "done_when": "When they answer",
                    "order": before,
                },
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertIn(marker, response.json["prompt"])
        self.assertIsNone(response.json["step_id"])
        self.assertEqual(Step.objects.filter(exercise=exercise).count(), before)
        self.assertFalse(Step.objects.filter(title="Brand new step").exists())

    def test_non_state_machine_formatter_uses_override_list(self):
        exercise = self._exercise()
        text = _get_formatted_exercise_steps_text(
            exercise,
            {},
            only_index=0,
            steps=[
                SimpleNamespace(
                    title="Override title",
                    description="Override description",
                    instructions="UNSAVED-FORMATTER",
                    done_when="done",
                    completion_prompt="",
                    reference_material="",
                    order=0,
                    id="step_override",
                )
            ],
        )
        self.assertIn("UNSAVED-FORMATTER", text)
        self.assertNotIn(exercise.steps.order_by("order").first().instructions, text)

    def test_failed_model_call_leaves_no_session_or_summary(self):
        exercise = self._exercise()
        step = exercise.steps.order_by("order").first()
        consumer = self.consumer_one
        summaries_before = ExerciseSummary.all_objects.filter(
            consumer=consumer, exercise=exercise
        ).count()
        before_ids = set(
            Session.all_objects.filter(subject="Dry run").values_list("id", flat=True)
        )

        with mock.patch("api.utils.AI.AI.ask") as ask:
            ask.side_effect = RuntimeError("model down")
            response = self._post(
                f"/exercises/{exercise.id}/steps/{step.id}/dry-run",
                {"consumer_id": consumer.user_id},
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY, response.json)
        ask.assert_called_once()

        created = Session.all_objects.filter(subject="Dry run").exclude(id__in=before_ids)
        self.assertTrue(created.exists())
        self.assertFalse(Session.objects.filter(subject="Dry run").exclude(id__in=before_ids).exists())
        for session in created:
            self.assertIsNotNone(session.deleted_at)
            self.assertFalse(session.completed)
            rows = SessionStep.all_objects.filter(session=session)
            self.assertTrue(rows.exists())
            self.assertTrue(all(row.deleted_at is not None for row in rows))
            self.assertFalse(Message.objects.filter(session=session).exists())

        self.assertEqual(
            ExerciseSummary.all_objects.filter(consumer=consumer, exercise=exercise).count(),
            summaries_before,
        )
