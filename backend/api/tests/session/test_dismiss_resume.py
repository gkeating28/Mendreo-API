from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status

from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...tests.TestCase import TestCase
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse
from ..utils.manager import Auth, General


def _paused(consumer, exercise, **extra):
    fields = dict(
        consumer=consumer,
        exercise=exercise,
        completed=False,
        abandoned=False,
        current_step_no=1,
        total_steps_no=exercise.steps_no or 1,
        state=Constants.SESSION_STATE_STEP_ACTIVE,
    )
    fields.update(extra)
    session = Session.objects.create(**fields)
    SessionStep.create(session, exercise)
    Participant.create_participants(session)
    return session


def _reply():
    return (
        ExerciseStateResponse(
            text="I'm here with you.",
            reasoning="test",
            suggested_responses=[],
            step_goal_met=False,
            asks_readiness=False,
        ),
        {},
        None,
        None,
    )


class DismissResumeTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.token = Auth.get_access_token(self.consumer.user)
        self.exercise = General.create_exercise()
        self.session = _paused(self.consumer, self.exercise)

    def _dismiss(self, session_id=None, token=None):
        return self._post(
            f"/sessions/{session_id or self.session.id}/dismiss-resume",
            {},
            token or self.token,
        )

    def test_another_consumers_session_is_404(self):
        other = Auth.create_consumer()
        token = Auth.get_access_token(other.user)
        response = self._dismiss(token=token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.json)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.resume_dismissed_at)

    def test_dismiss_is_idempotent_and_leaves_updated_at(self):
        past = timezone.now() - timedelta(days=1)
        Session.objects.filter(pk=self.session.pk).update(updated_at=past)
        detail = self._get(f"/sessions/{self.session.id}", access_token=self.token)
        first = self._dismiss()
        second = self._dismiss()
        self.session.refresh_from_db()
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.json)
        self.assertEqual(set(first.json.keys()), set(detail.json.keys()))
        self.assertTrue(first.json["resume_dismissed"])
        self.assertTrue(second.json["resume_dismissed"])
        self.assertNotIn("resume_dismissed_at", first.json)
        self.assertEqual(self.session.updated_at, past)
        self.assertIsNotNone(self.session.resume_dismissed_at)
        self.assertFalse(self.session.completed)
        self.assertFalse(self.session.abandoned)
        self.assertEqual(self.session.current_step_no, 1)

    def test_completed_abandoned_and_general_are_refused(self):
        completed = _paused(self.consumer, self.exercise, completed=True)
        abandoned = _paused(self.consumer, self.exercise, abandoned=True)
        general = Session.objects.create(
            consumer=self.consumer,
            exercise=None,
            completed=False,
            abandoned=False,
        )
        Participant.create_participants(general)
        for session in (completed, abandoned, general):
            response = self._dismiss(session.id)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)
            session.refresh_from_db()
            self.assertIsNone(session.resume_dismissed_at)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_a_new_message_clears_it(self):
        past = timezone.now() - timedelta(days=1)
        Session.objects.filter(pk=self.session.pk).update(
            updated_at=past,
            resume_dismissed_at=timezone.now(),
        )
        with patch("api.utils.Agent.get_response", return_value=_reply()):
            response = self._post(
                "/messages",
                {"session": self.session.id, "text": "I'm back"},
                self.token,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.resume_dismissed_at)
        self.assertGreater(self.session.updated_at, past)

    def test_list_start_and_detail_expose_resume_dismissed(self):
        listed = self._get("/sessions", access_token=self.token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        rows = listed.json["results"] if isinstance(listed.json, dict) else listed.json
        row = next(item for item in rows if item["id"] == self.session.id)
        self.assertIs(row["resume_dismissed"], False)
        detail = self._get(f"/sessions/{self.session.id}", access_token=self.token)
        self.assertIs(detail.json["resume_dismissed"], False)
        started = self._get(
            "/sessions/start",
            query_params_dict={"exercise_id": self.exercise.id},
            access_token=self.token,
        )
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
        self.assertEqual(started.json["id"], self.session.id)
        self.assertIs(started.json["resume_dismissed"], False)
        self._dismiss()
        detail = self._get(f"/sessions/{self.session.id}", access_token=self.token)
        self.assertIs(detail.json["resume_dismissed"], True)
        self.assertIn("phase", detail.json)
        self.assertIn("exercise", detail.json)
        self.assertIn("session_state", detail.json)
