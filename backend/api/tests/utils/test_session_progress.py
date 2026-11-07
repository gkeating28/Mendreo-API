from django.test import TestCase
from django.utils import timezone

from api.agent.models import Agent
from api.consumer.models import Consumer
from api.exercise.models import Exercise
from api.image.models import Image
from api.session.models import Session, SessionStep
from api.session.serializers import SessionDetailSerializer, SessionListSerializer
from api.step.models import Step
from api.user.models import User
from api.utils import Constants
from api.utils.session_progress import session_progress


def _consumer():
    user = User.objects.create(
        email=f"progress-{User.objects.count()}@example.com",
        type=Constants.USER_TYPE_CONSUMER,
        first_name="Progress",
        last_name="Test",
        password="x",
    )
    image = Image.objects.create(
        created_by=user,
        original="original",
        name="avatar",
        width=1,
        height=1,
    )
    agent = Agent.objects.create(
        avatar=image,
        created_by=user,
        name="Toni",
        description="Guide",
    )
    return Consumer.objects.create(user=user, agent=agent)


def _exercise(step_count=3):
    exercise = Exercise.objects.create(
        title="Think flexibly",
        subtitle="One thought",
        description="Work through one thought.",
        status=Constants.EXERCISE_STATUS_DRAFT,
        steps_no=step_count,
        icon="leaf",
        icon_background_color="tan",
    )
    for index in range(step_count):
        Step.objects.create(
            exercise=exercise,
            title=f"Step {index + 1}",
            description="Describe it",
            instructions="Ask them",
            completion_label=f"Label {index + 1}",
            order=index,
        )
    return exercise


def _run(consumer, exercise, *, stored_step, completed_count, finished=False):
    session = Session.objects.create(
        consumer=consumer,
        exercise=exercise,
        completed=finished,
        completed_at=timezone.now() if finished else None,
        current_step_no=stored_step,
        total_steps_no=exercise.steps_no,
    )
    SessionStep.create(session, exercise)
    rows = list(session.session_steps.order_by("order"))
    for row in rows[:completed_count]:
        row.completed = True
        row.save(update_fields=["completed", "updated_at"])
    session.refresh_from_db()
    return session


class SessionProgressHelperTests(TestCase):
    def setUp(self):
        self.consumer = _consumer()
        self.exercise = _exercise(3)

    def test_check_in_is_step_zero(self):
        session = _run(self.consumer, self.exercise, stored_step=0, completed_count=0)

        progress = session_progress(session)

        self.assertEqual(progress.completed_steps, 0)
        self.assertEqual(progress.total_steps, 3)
        self.assertEqual(progress.current_step_no, 0)

    def test_mid_run_uses_completed_rows_not_the_stored_step(self):
        session = _run(self.consumer, self.exercise, stored_step=1, completed_count=1)

        progress = session_progress(session)

        self.assertEqual(session.current_step_no, 1)
        self.assertEqual(progress.completed_steps, 1)
        self.assertEqual(progress.total_steps, 3)
        self.assertEqual(progress.current_step_no, 2)

    def test_last_step_stays_on_the_open_step(self):
        session = _run(self.consumer, self.exercise, stored_step=3, completed_count=2)

        progress = session_progress(session)

        self.assertFalse(session.completed)
        self.assertEqual(progress.completed_steps, 2)
        self.assertEqual(progress.total_steps, 3)
        self.assertEqual(progress.current_step_no, 3)

    def test_finished_run_is_one_past_the_last_step(self):
        session = _run(
            self.consumer,
            self.exercise,
            stored_step=3,
            completed_count=3,
            finished=True,
        )

        progress = session_progress(session)

        self.assertEqual(progress.completed_steps, 3)
        self.assertEqual(progress.total_steps, 3)
        self.assertEqual(progress.current_step_no, 4)

    def test_general_chat_keeps_a_null_step(self):
        session = Session.objects.create(consumer=self.consumer)

        progress = session_progress(session)

        self.assertEqual(progress.completed_steps, 0)
        self.assertEqual(progress.total_steps, 0)
        self.assertIsNone(progress.current_step_no)


class SessionProgressSerializerTests(TestCase):
    def setUp(self):
        self.consumer = _consumer()
        self.exercise = _exercise(3)

    def test_list_and_detail_expose_helper_fields_and_keep_existing_ones(self):
        session = _run(self.consumer, self.exercise, stored_step=1, completed_count=1)

        listed = SessionListSerializer(session).data
        detail = SessionDetailSerializer(session).data

        for data in (listed, detail):
            self.assertEqual(data["completed_steps"], 1)
            self.assertEqual(data["total_steps"], 3)
            self.assertEqual(data["current_step_no"], 2)
            self.assertEqual(data["total_steps_no"], 3)
            self.assertEqual(data["id"], session.id)
            self.assertIn("phase", data)
            self.assertIn("completed", data)
            self.assertIn("exercise", data)
            self.assertIn("pre_exercise", data)

        step_numbers = [step["step_no"] for step in detail["steps"]]
        self.assertEqual(step_numbers, [1, 2, 3])
        state = detail["session_state"]
        self.assertEqual(state["current_step_no"], 2)
        self.assertEqual(session.current_step_no, 1)
        self.assertEqual(
            [step["status"] for step in state["steps"]],
            ["completed", "active", "pending"],
        )
        self.assertIn("phase", state)
        self.assertIn("pending_action", state)
        self.assertIn("session_id", state)
        first = detail["steps"][0]
        self.assertTrue(first["completed"])
        self.assertIn("completion_label", first)
        self.assertIn("completion_result", first)
        self.assertIn("result_confidence", first)
        self.assertIn("last_asset", first)
        self.assertIn("step", first)

    def test_detail_check_in_last_step_and_finished(self):
        check_in = _run(self.consumer, self.exercise, stored_step=0, completed_count=0)
        last = _run(self.consumer, self.exercise, stored_step=3, completed_count=2)
        finished = _run(
            self.consumer,
            self.exercise,
            stored_step=3,
            completed_count=3,
            finished=True,
        )

        self.assertEqual(SessionDetailSerializer(check_in).data["current_step_no"], 0)
        self.assertEqual(SessionDetailSerializer(last).data["current_step_no"], 3)
        self.assertEqual(SessionDetailSerializer(finished).data["current_step_no"], 4)
        self.assertEqual(SessionDetailSerializer(finished).data["completed_steps"], 3)
