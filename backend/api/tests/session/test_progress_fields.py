from unittest.mock import patch

from rest_framework import status

from ..utils.manager import Auth
from ...exercise.models import Exercise
from ...session.models import Session, SessionStep
from ...step.models import Step
from ...tests.TestCase import TestCase
from ...utils import Constants


def _exercise():
    exercise = Exercise.objects.create(
        title="Think flexibly",
        subtitle="One thought",
        description="Work through one thought.",
        status=Constants.EXERCISE_STATUS_DRAFT,
        steps_no=3,
        icon="leaf",
        icon_background_color="tan",
    )
    for index in range(3):
        Step.objects.create(
            exercise=exercise,
            title=f"Step {index + 1}",
            description="Describe it",
            instructions="Ask them",
            completion_label=f"Label {index + 1}",
            order=index,
        )
    return exercise


def _paused(consumer, exercise):
    session = Session.objects.create(
        consumer=consumer,
        exercise=exercise,
        completed=False,
        current_step_no=1,
        total_steps_no=3,
    )
    SessionStep.create(session, exercise)
    first = session.session_steps.order_by("order").first()
    first.completed = True
    first.completion_label = "Label 1"
    first.save(update_fields=["completed", "completion_label", "updated_at"])
    return session


class SessionProgressApiTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.exercise = _exercise()
        self.session = _paused(self.consumer, self.exercise)

    def _results(self, response):
        body = response.json
        if isinstance(body, dict) and "results" in body:
            return body["results"]
        return body

    def _assert_paused_progress(self, data):
        self.assertEqual(data["id"], self.session.id)
        self.assertEqual(data["completed_steps"], 1)
        self.assertEqual(data["total_steps"], 3)
        self.assertEqual(data["current_step_no"], 2)
        self.assertEqual(data["total_steps_no"], 3)
        self.assertEqual(data["completed"], False)
        self.assertEqual(data["phase"], "exercise")
        self.assertIsNotNone(data["exercise"])
        self.assertIn("pre_exercise", data)
        self.assertIn("messages_no", data)

    def test_list_detail_and_start_share_the_helper_fields(self):
        listed = self._get("/sessions", access_token=self.token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        match = next(row for row in self._results(listed) if row["id"] == self.session.id)
        self._assert_paused_progress(match)
        self.assertNotIn("steps", match)

        detail = self._get(f"/sessions/{self.session.id}", access_token=self.token)
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        self._assert_paused_progress(detail.json)
        self.assertEqual([step["step_no"] for step in detail.json["steps"]], [1, 2, 3])
        self.assertEqual(
            [step["completed"] for step in detail.json["steps"]],
            [True, False, False],
        )
        self.assertEqual(detail.json["steps"][0]["completion_label"], "Label 1")
        self.assertIn("completion_result", detail.json["steps"][0])
        self.assertIn("result_confidence", detail.json["steps"][0])

        with patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None):
            started = self._get(
                "/sessions/start",
                query_params_dict={"exercise_id": self.exercise.id},
                access_token=self.token,
            )
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
        self._assert_paused_progress(started.json)
        self.assertEqual([step["step_no"] for step in started.json["steps"]], [1, 2, 3])

    def test_detail_and_start_stay_on_the_requesting_user(self):
        other = Auth.create_consumer()
        other_token = Auth.get_access_token(other.user)

        hidden = self._get(f"/sessions/{self.session.id}", access_token=other_token)
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

        with patch("api.utils.AIWorkerClient.request_session_greeting", return_value=None):
            started = self._get(
                "/sessions/start",
                query_params_dict={"exercise_id": self.exercise.id},
                access_token=other_token,
            )
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
        self.assertNotEqual(started.json["id"], self.session.id)
        resumed = Session.objects.get(id=started.json["id"])
        self.assertEqual(resumed.consumer_id, other.user_id)
        self.session.refresh_from_db()
        self.assertFalse(self.session.abandoned)
        self.assertEqual(self.session.consumer_id, self.consumer.user_id)
