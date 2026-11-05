from datetime import datetime, timezone as dt_timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from api.management.commands.backfill_message_step_no import backfill_session
from api.message.models import Message
from api.participant.models import Participant
from api.session.models import Session, SessionStep
from api.tests.utils.test_session_progress import _consumer, _exercise


def _at(minute):
    return datetime(2026, 9, 25, 11, minute, tzinfo=dt_timezone.utc)


def _row(session, sender, text, minute, *, label="", step_no=None):
    message = Message.objects.create(session=session, sender=sender, text=text)
    Message.objects.filter(id=message.id).update(
        created_at=_at(minute),
        completion_label=label or None,
        step_no=step_no,
    )
    message.refresh_from_db()
    return message


class BackfillMessageStepNoTests(TestCase):
    def setUp(self):
        self.consumer = _consumer()
        self.exercise = _exercise(2)
        self.session = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=True,
            current_step_no=3,
            total_steps_no=2,
            pre_exercise_completed_at=_at(1),
        )
        SessionStep.create(self.session, self.exercise)
        self.user, self.agent = Participant.create_participants(self.session)

    def _thread(self):
        return {
            "check_in": _row(self.session, self.agent, "Welcome back.", 0),
            "ask": _row(self.session, self.agent, "What is the worry?", 2),
            "answer": _row(self.session, self.user, "Getting fired", 3),
            "close": _row(
                self.session,
                self.agent,
                "Are you ready to continue?",
                5,
                label="You have described it",
            ),
            "yes": _row(self.session, self.user, "Yes, I'm ready", 6),
            "next": _row(self.session, self.agent, "What time of day?", 7),
            "empty": _row(self.session, self.user, "  ", 8),
            "kept": _row(self.session, self.agent, "Already numbered", 4, step_no=7),
        }

    def _run(self, *args):
        out = StringIO()
        call_command("backfill_message_step_no", *args, stdout=out)
        return out.getvalue()

    def test_places_check_in_and_label_walk_and_leaves_the_rest_null(self):
        rows = self._thread()

        output = self._run()

        for key in ("check_in", "ask", "answer", "close", "yes", "next", "empty", "kept"):
            rows[key].refresh_from_db()
        self.assertEqual(rows["check_in"].step_no, 0)
        self.assertEqual(rows["ask"].step_no, 1)
        self.assertEqual(rows["answer"].step_no, 1)
        self.assertEqual(rows["close"].step_no, 1)
        self.assertEqual(rows["yes"].step_no, 1)
        self.assertEqual(rows["next"].step_no, 2)
        self.assertIsNone(rows["empty"].step_no)
        self.assertEqual(rows["kept"].step_no, 7)
        self.assertIn("placed: 6", output)
        self.assertIn("left null: 1", output)
        self.assertIn("sessions touched: 1", output)

        again = self._run()
        rows["kept"].refresh_from_db()
        rows["empty"].refresh_from_db()
        self.assertEqual(rows["kept"].step_no, 7)
        self.assertIsNone(rows["empty"].step_no)
        self.assertIn("placed: 0", again)
        self.assertIn("left null: 1", again)

    def test_dry_run_and_session_id_do_not_write_other_sessions(self):
        rows = self._thread()
        other = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=False,
            current_step_no=1,
            total_steps_no=2,
        )
        outsider = _row(other, self.agent, "Other run", 2)

        dry = self._run("--dry-run", "--session-id", self.session.id)
        rows["ask"].refresh_from_db()
        outsider.refresh_from_db()
        self.assertIsNone(rows["ask"].step_no)
        self.assertIsNone(outsider.step_no)
        self.assertIn("placed: 6", dry)
        self.assertIn("sessions touched: 1", dry)

        self._run("--session-id", self.session.id)
        outsider.refresh_from_db()
        rows["ask"].refresh_from_db()
        self.assertEqual(rows["ask"].step_no, 1)
        self.assertIsNone(outsider.step_no)

    def test_general_chat_stays_null(self):
        chat = Session.objects.create(consumer=self.consumer)
        user, _agent = Participant.create_participants(chat)
        message = Message.objects.create(session=chat, sender=user, text="Hello")
        self.assertIsNone(message.step_no)

        placed, left = backfill_session(chat, dry_run=False)

        message.refresh_from_db()
        self.assertEqual(placed, 0)
        self.assertEqual(left, 1)
        self.assertIsNone(message.step_no)
