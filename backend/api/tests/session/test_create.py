from rest_framework import status

from ...participant.models import Participant
from ...session.models import Session
from ...tests.TestCase import TestCase
from ..utils.manager import Auth, General


class CreateTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.admin = Auth.create_admin()
        self.admin_access_token = Auth.get_access_token(self.admin.user)

    def test_creates_fresh_general_session(self):
        existing = General.create_session(consumer=self.consumer)

        response = self._post("/sessions", {}, access_token=self.access_token)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.json["id"], existing.id)
        self.assertIsNone(response.json["exercise"])
        self.assertIsNone(response.json["last_message"])
        self.assertEqual(response.json["phase"], "general")

        session = Session.objects.get(id=response.json["id"])
        self.assertEqual(session.consumer_id, self.consumer.user_id)
        self.assertIsNone(session.exercise_id)
        self.assertEqual(
            Participant.objects.filter(session=session).count(),
            2,
        )

    def test_second_post_creates_another_session(self):
        first = self._post("/sessions", {}, access_token=self.access_token)
        second = self._post("/sessions", {}, access_token=self.access_token)

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.json["id"], second.json["id"])
        self.assertEqual(
            Session.objects.filter(consumer=self.consumer, exercise__isnull=True).count(),
            2,
        )

    def test_admin_cannot_create(self):
        response = self._post("/sessions", {}, access_token=self.admin_access_token)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_create(self):
        response = self._post("/sessions", {})
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
