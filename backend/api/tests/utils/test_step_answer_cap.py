from django.test import TestCase

from api.message.models import Message
from api.participant.models import Participant
from api.session.models import Session, SessionStep
from api.tests.utils.test_session_progress import _consumer, _exercise
from api.utils import Constants
from api.utils.turn_hint import (
    EXERCISE_NUDGE_HINT,
    STEP_ANSWER_CAP,
    SUMMARY_CONFIRM_HINT,
    step_progress_hint,
    user_prompt_with_hint,
)


class StepAnswerCapTests(TestCase):
    def setUp(self):
        self.consumer = _consumer()
        self.exercise = _exercise(2)
        self.session = Session.objects.create(
            consumer=self.consumer,
            exercise=self.exercise,
            completed=False,
            current_step_no=1,
            total_steps_no=2,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        self.user, self.agent = Participant.create_participants(self.session)

    def _reply(self, text="I keep worrying about losing my job"):
        return Message.objects.create(session=self.session, sender=self.user, text=text)

    def _replies(self, count):
        return [self._reply() for _ in range(count)]

    def test_no_hint_at_five_replies(self):
        Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="What is the worry?",
        )
        replies = self._replies(5)
        self.assertEqual(STEP_ANSWER_CAP, 6)
        self.assertEqual([row.step_no for row in replies], [1, 1, 1, 1, 1])

        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertNotIn("<TURN_HINT>", prompted)
        self.assertEqual(prompted, replies[-1].text)

    def test_hint_at_six_replies(self):
        replies = self._replies(6)

        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertTrue(prompted.startswith(replies[-1].text))

    def test_check_in_messages_are_not_counted(self):
        self.session.current_step_no = 0
        self.session.save(update_fields=["current_step_no", "updated_at"])
        check_in = self._replies(6)
        self.assertEqual({row.step_no for row in check_in}, {0})
        Message.objects.filter(pk=check_in[0].pk).update(step_no=None)
        self.session.current_step_no = 1
        self.session.pre_exercise_completed_at = check_in[-1].created_at
        self.session.save(
            update_fields=["current_step_no", "pre_exercise_completed_at", "updated_at"]
        )

        replies = self._replies(5)
        self.assertEqual([row.step_no for row in replies], [1, 1, 1, 1, 1])
        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertEqual(prompted, replies[-1].text)

    def test_earlier_step_messages_are_not_counted(self):
        earlier = self._replies(6)
        self.assertEqual({row.step_no for row in earlier}, {1})
        Message.objects.filter(pk=earlier[0].pk).update(step_no=None)
        SessionStep.create(self.session, self.exercise)
        first = self.session.session_steps.get(order=0)
        first.completed = True
        first.save(update_fields=["completed", "updated_at"])
        self.session.current_step_no = 2
        self.session.save(update_fields=["current_step_no", "updated_at"])

        replies = self._replies(5)
        self.assertEqual([row.step_no for row in replies], [2, 2, 2, 2, 2])
        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertEqual(prompted, replies[-1].text)

    def test_general_chat_is_unaffected(self):
        general = Session.objects.create(consumer=self.consumer, exercise=None)
        user, _agent = Participant.create_participants(general)
        replies = [
            Message.objects.create(
                session=general,
                sender=user,
                text="I keep worrying about losing my job",
            )
            for _ in range(6)
        ]
        self.assertEqual({row.step_no for row in replies}, {None})
        self.assertIsNone(step_progress_hint(general, replies[-1]))

        prompted = user_prompt_with_hint(general, replies[-1])

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertIn(EXERCISE_NUDGE_HINT, prompted)

    def test_existing_goal_hint_still_wins(self):
        hint = "Ask one question that would supply what is still missing: the situation"
        self.session.cached_prompt_meta = {"goal_hint": hint}
        self.session.save(update_fields=["cached_prompt_meta", "updated_at"])
        replies = self._replies(6)

        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertIn(hint, prompted)
        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.session.refresh_from_db()
        self.assertNotIn("goal_hint", self.session.cached_prompt_meta or {})

    def _summary(self):
        return Message.objects.create(
            session=self.session,
            sender=self.agent,
            text=(
                "You said the worry is losing your job and the effect is anxiety about bills. "
                "Have I got that right?"
            ),
        )

    def test_yes_after_a_summary_gets_no_hint(self):
        self._replies(6)
        self._summary()
        yes = self._reply("yes")

        prompted = user_prompt_with_hint(self.session, yes)

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertNotIn("<TURN_HINT>", prompted)
        self.assertEqual(prompted, "yes")

    def test_no_after_a_summary_gets_no_hint(self):
        self._replies(6)
        self._summary()
        no = self._reply("no, not quite")

        prompted = user_prompt_with_hint(self.session, no)

        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertNotIn("<TURN_HINT>", prompted)
        self.assertEqual(prompted, "no, not quite")

    def test_hint_returns_after_a_normal_question(self):
        self._replies(6)
        self._summary()
        self._reply("no, not quite")
        Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="What else happens in that situation?",
        )
        again = self._reply("I fall behind on the bills")

        prompted = user_prompt_with_hint(self.session, again)

        self.assertIn(SUMMARY_CONFIRM_HINT, prompted)
        self.assertTrue(prompted.startswith(again.text))
