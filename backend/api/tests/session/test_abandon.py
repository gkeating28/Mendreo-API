from unittest import mock

from rest_framework import status

from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...tests.TestCase import TestCase
from ..utils.manager import Auth, General


class AbandonPausedRunTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.exercise = General.create_exercise()

    @mock.patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None)
    def test_restart_abandons_paused_run_and_keeps_answers(self, _greeting):
        paused = General.start_session(consumer=self.consumer, exercise=self.exercise)
        step = paused.session_steps.order_by("order").first()
        self.assertIsNotNone(step)
        step.completed = True
        step.completion_result = "I'll fail the exam"
        step.save(update_fields=["completed", "completion_result"])

        sender = Participant.objects.filter(
            session=paused, consumer=self.consumer
        ).first()
        Message.objects.create(
            session=paused,
            sender=sender,
            text="I'll fail the exam",
        )

        response = self._get(
            "/sessions/start",
            query_params_dict={
                "exercise_id": self.exercise.id,
                "restart": "true",
            },
            access_token=self.access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertNotEqual(response.json["id"], paused.id)
        self.assertFalse(response.json.get("abandoned"))

        paused.refresh_from_db()
        self.assertTrue(paused.abandoned)
        self.assertFalse(paused.completed)
        self.assertEqual(
            SessionStep.objects.get(id=step.id).completion_result,
            "I'll fail the exam",
        )
        self.assertTrue(
            Message.objects.filter(session=paused, text="I'll fail the exam").exists()
        )

        resumed = General.start_session(consumer=self.consumer, exercise=self.exercise)
        self.assertEqual(resumed.id, response.json["id"])
        self.assertFalse(resumed.abandoned)

    @mock.patch("api.utils.AIWorkerClient._run_session_greeting", return_value=None)
    def test_start_without_restart_resumes_paused_run(self, _greeting):
        paused = General.start_session(consumer=self.consumer, exercise=self.exercise)
        resumed = General.start_session(consumer=self.consumer, exercise=self.exercise)
        self.assertEqual(paused.id, resumed.id)
        self.assertEqual(Session.objects.filter(exercise=self.exercise).count(), 1)
