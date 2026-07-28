from unittest import mock

from django.test import override_settings
from rest_framework import status

from ...tests.TestCase import TestCase
from ...message.models import Message
from ..utils import Data
from ..utils.manager import Auth, General


class MessageCommitBeforeWorkerTest(TestCase):
    """POST /messages must commit the user row before calling the AI worker."""

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_access_token(self.consumer.user)
        self.session = General.create_session(consumer=self.consumer)

    @override_settings(AI_ASYNC_MESSAGES=False)
    def test_worker_sees_committed_message(self):
        seen = {}

        def fake_worker(user_message, session):
            # Separate "connection" check: row must already be queryable.
            seen["exists"] = Message.objects.filter(id=user_message.id).exists()
            seen["id"] = user_message.id
            return user_message

        data = Data.valid_message_data(session=self.session, text="Hello there")

        with mock.patch(
            "api.message.views.request_agent_response",
            side_effect=fake_worker,
        ) as mocked:
            response = self._post(
                "/messages",
                data,
                access_token=self.consumer_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mocked.assert_called_once()
        self.assertTrue(seen.get("exists"))
        self.assertEqual(seen.get("id"), response.json["id"])

    @override_settings(AI_ASYNC_MESSAGES=True)
    def test_async_enqueues_after_commit(self):
        seen = {}

        def fake_enqueue(user_message):
            seen["exists"] = Message.objects.filter(id=user_message.id).exists()
            seen["id"] = user_message.id

        data = Data.valid_message_data(session=self.session, text="Async hello")

        with mock.patch(
            "api.message.views.enqueue_agent_response",
            side_effect=fake_enqueue,
        ) as mocked:
            response = self._post(
                "/messages",
                data,
                access_token=self.consumer_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mocked.assert_called_once()
        self.assertTrue(seen.get("exists"))
        self.assertEqual(seen.get("id"), response.json["id"])
        self.assertTrue(response.json.get("ai_pending"))
        self.assertEqual(response.json["text"], "Async hello")
