from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ..TestCase import TestCase
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep


class ReflectRunApiTests(BaseTest):
    def endpoint(self):
        return "runs"

    def _complete_run(self, finding="The team restructure in October"):
        exercise = General.create_exercise()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        SessionStep.create(session, exercise)
        Session.objects.filter(id=session.id).update(
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )
        session.refresh_from_db()
        consumer_pt, agent_pt = Participant.create_participants(session)
        step = session.session_steps.order_by("order").first()
        if step:
            step.completed = True
            step.completion_result = finding
            step.save(update_fields=["completed", "completion_result", "updated_at"])
        first = Message.objects.create(session=session, sender=agent_pt, text="What's the worry?")
        second = Message.objects.create(session=session, sender=consumer_pt, text=finding)
        Message.objects.filter(id=first.id).update(step_no=1)
        Message.objects.filter(id=second.id).update(step_no=1)
        return session, exercise

    def test_list_completed_runs_and_save_reflection(self):
        session, exercise = self._complete_run()
        listed = TestCase._get(
            "/runs",
            query_params_dict={"status": "completed"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(listed.json["count"], 1)
        run = listed.json["results"][0]
        self.assertEqual(run["id"], session.id)
        self.assertEqual(run["exerciseId"], exercise.id)
        self.assertEqual(run["topic"], "The team restructure in October")
        self.assertEqual(run["basis"], "Work")
        self.assertFalse(run["steps"][0].get("transcript"))

        detail = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        self.assertGreaterEqual(len(detail.json["steps"][0]["transcript"]), 1)

        step_id = detail.json["steps"][0]["stepId"]
        saved = TestCase._put(
            f"/runs/{session.id}/reflections/{step_id}",
            {"text": "It still shows up on Sunday nights."},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(saved.status_code, status.HTTP_200_OK, getattr(saved, "json", saved))
        self.assertEqual(saved.json["stepId"], step_id)
        self.assertIn("Sunday", saved.json["text"])

        again = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(len(again.json["reflections"]), 1)

        cleared = TestCase._put(
            f"/runs/{session.id}/reflections/{step_id}",
            {"text": "  "},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(cleared.status_code, status.HTTP_200_OK, cleared.json)
        empty = TestCase._get(
            f"/runs/{session.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(empty.json["reflections"], [])

    def test_in_progress_runs_are_hidden(self):
        exercise = General.create_exercise()
        Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=False,
            current_step_no=1,
            total_steps_no=exercise.steps_no,
        )
        listed = TestCase._get(
            "/runs",
            query_params_dict={"status": "completed"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(listed.json["count"], 0)
