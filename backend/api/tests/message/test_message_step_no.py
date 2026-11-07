from unittest.mock import patch

from django.test import TestCase

from api.message.models import Message
from api.message.serializers import MessageCreateSerializer, MessageDetailSerializer, MessageListSerializer
from api.participant.models import Participant
from api.session.models import Session, SessionStep
from api.tests.utils.test_session_progress import _consumer, _exercise
from api.utils.SessionStateMachine import _confirm


class MessageStepNoTests(TestCase):
    def setUp(self):
        self.consumer = _consumer()
        self.exercise = _exercise(2)
        self.session = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=False,
            current_step_no=1,
            total_steps_no=2,
        )
        SessionStep.create(self.session, self.exercise)
        self.user, self.agent = Participant.create_participants(self.session)

    def test_user_agent_and_next_greeting_keep_the_step_order(self):
        user_message = Message.objects.create(
            session=self.session,
            sender=self.user,
            text="Yes",
        )
        agent_message = Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="Are you ready to move on?",
        )
        user_message.refresh_from_db()
        agent_message.refresh_from_db()
        self.assertEqual(user_message.step_no, 1)
        self.assertEqual(agent_message.step_no, 1)

        def greeting(session, synthetic_text=None):
            return Message.objects.create(
                session=session,
                sender=self.agent,
                text=synthetic_text or "Next step",
            )

        with (
            patch(
                "api.utils.AIWorkerClient.request_session_greeting",
                side_effect=greeting,
            ),
            patch(
                "api.utils.extraction.extract_step_result",
                return_value={"value": "a named thought", "confidence": 0.9},
            ),
        ):
            _confirm(self.session, user_message)

        user_message.refresh_from_db()
        agent_message.refresh_from_db()
        opened = (
            Message.objects.filter(session=self.session)
            .exclude(id__in=[user_message.id, agent_message.id])
            .get()
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.current_step_no, 2)
        self.assertEqual(user_message.step_no, 1)
        self.assertEqual(agent_message.step_no, 1)
        self.assertEqual(opened.step_no, 2)

    def test_check_in_message_is_step_zero(self):
        self.session.current_step_no = 0
        self.session.save(update_fields=["current_step_no", "updated_at"])

        message = Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="How did last time go?",
        )

        message.refresh_from_db()
        self.assertEqual(message.step_no, 0)
        listed = MessageListSerializer(message).data
        detail = MessageDetailSerializer(message).data
        self.assertEqual(listed["step_no"], 0)
        self.assertEqual(detail["step_no"], 0)
        self.assertNotIn("step_no", MessageCreateSerializer.Meta.fields)

    def test_explicit_step_and_bulk_create(self):
        pinned = Message.objects.create(
            session=self.session,
            sender=self.user,
            text="Pinned",
            step_no=4,
        )
        pinned.refresh_from_db()
        self.assertEqual(pinned.step_no, 4)

        self.session.current_step_no = 2
        self.session.save(update_fields=["current_step_no", "updated_at"])
        created = Message.objects.bulk_create(
            [
                Message(session=self.session, sender=self.user, text="One"),
                Message(session=self.session, sender=self.agent, text="Two"),
            ]
        )
        stored = list(
            Message.objects.filter(id__in=[row.id for row in created]).order_by("created_at", "id")
        )
        self.assertEqual([row.step_no for row in stored], [2, 2])
