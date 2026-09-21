from unittest import mock

from freezegun import freeze_time

from ...message.models import Message
from ...participant.models import Participant
from ...setting.models import Setting
from ...tests.TestCase import TestCase
from ...utils.Agent import _get_formatted_exercise_steps_text, _prepare_prompt
from ...utils.MessageFlow import apply_agent_response
from ...utils.StepProgress import session_step_total
from ..utils.manager import Auth, General


class MessageFlowLastStepTests(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch(
            "api.utils.AIWorkerClient._run_session_greeting", return_value=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.consumer = Auth.create_consumer()
        self.exercise = General.create_exercise()
        self.session = General.start_session(
            consumer=self.consumer, exercise=self.exercise
        )
        self.consumer_pt = Participant.objects.filter(
            session=self.session, consumer=self.consumer
        ).first()
        self.agent_pt = Participant.objects.filter(
            session=self.session, agent=self.consumer.agent
        ).first()

    def _complete_current_step(self):
        user_message = Message.objects.create(
            session=self.session,
            sender=self.consumer_pt,
            text="Yes",
        )
        agent_message = Message.objects.create(
            session=self.session,
            sender=self.agent_pt,
            text="On to the next step.",
            is_step_complete=True,
            completion_result="named worry",
        )
        return apply_agent_response(user_message, agent_message)

    def test_last_catalogue_step_advances_onto_the_summary_page(self):
        total = self.exercise.steps.count()
        self.session.current_step_no = total
        self.session.total_steps_no = total
        self.session.save(update_fields=["current_step_no", "total_steps_no"])

        self._complete_current_step()
        self.session.refresh_from_db()

        self.assertTrue(self.session.completed)
        self.assertEqual(self.session.current_step_no, total + 1)

    def test_stale_total_does_not_end_before_the_last_catalogue_step(self):
        live = self.exercise.steps.count()
        self.assertGreaterEqual(live, 3)
        self.session.current_step_no = live - 1
        self.session.total_steps_no = live - 1
        self.session.save(update_fields=["current_step_no", "total_steps_no"])

        self.assertEqual(session_step_total(self.session), live)

        self._complete_current_step()
        self.session.refresh_from_db()

        self.assertFalse(self.session.completed)
        self.assertEqual(self.session.current_step_no, live)
        self.assertEqual(self.session.total_steps_no, live)


class ExercisePromptClockTests(TestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch(
            "api.utils.AIWorkerClient._run_session_greeting", return_value=None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        Setting.create_all()
        self.consumer = Auth.create_consumer()
        self.consumer.user.first_name = "Sean"
        self.consumer.user.save(update_fields=["first_name"])
        self.exercise = General.create_exercise()
        self.session = General.start_session(
            consumer=self.consumer, exercise=self.exercise
        )

    def test_prompt_interpolates_ireland_local_time_not_placeholder(self):
        # 08:30 UTC is 09:30 in Ireland during BST.
        with freeze_time("2026-09-21 08:30:00+00:00"):
            self.session.cached_prompt = None
            self.session.save(update_fields=["cached_prompt"])
            prompt = _prepare_prompt(self.session)

        self.assertNotIn("{today_date}", prompt)
        self.assertNotIn("{current_time}", prompt)
        self.assertIn("21 September, 2026", prompt)
        self.assertIn("09:30", prompt)
        self.assertIn("Europe/Dublin", prompt)
        self.assertIn("Never say goodnight", prompt)

    def test_rebuilds_cached_prompt_that_still_has_today_date_placeholder(self):
        self.session.cached_prompt = "Today is {today_date}. Goodnight."
        self.session.save(update_fields=["cached_prompt"])

        with freeze_time("2026-09-21 08:30:00+00:00"):
            prompt = _prepare_prompt(self.session)

        self.assertNotIn("{today_date}", prompt)
        self.assertIn("09:30", prompt)

    def test_last_catalogue_step_asks_for_the_summary_page(self):
        text = _get_formatted_exercise_steps_text(self.exercise)
        self.assertIn("Are you ready to see your summary?", text)
        self.assertIn("Do not wrap up with goodbye or a time-of-day sign-off", text)
