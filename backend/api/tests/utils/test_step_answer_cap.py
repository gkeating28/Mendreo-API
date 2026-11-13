from unittest.mock import patch

from django.test import TestCase

from api.message.models import Message
from api.participant.models import Participant
from api.session.models import Session, SessionStep
from api.tests.utils.test_session_progress import _consumer, _exercise
from api.utils import Constants
from api.utils.turn_hint import (
    EXERCISE_NUDGE_HINT,
    STEP_ANSWER_CAP,
    STEP_HARD_CAP,
    STEP_MISSING_HINT,
    STEP_READY_HINT,
    STEP_SUMMARY_HINT,
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

        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
        self.assertNotIn("<TURN_HINT>", prompted)
        self.assertEqual(prompted, replies[-1].text)

    def test_hint_at_six_replies(self):
        replies = self._replies(6)

        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(SUMMARY_CONFIRM_HINT, prompted)
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

        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
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

        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
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

        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
        self.assertIn(EXERCISE_NUDGE_HINT, prompted)

    def test_existing_goal_hint_still_wins(self):
        hint = "Ask one question that would supply what is still missing: the situation"
        self.session.cached_prompt_meta = {"goal_hint": hint}
        self.session.save(update_fields=["cached_prompt_meta", "updated_at"])
        replies = self._replies(6)

        prompted = user_prompt_with_hint(self.session, replies[-1])

        self.assertIn(hint, prompted)
        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
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

    def test_yes_after_a_summary_asks_if_ready(self):
        self._replies(6)
        self._summary()
        yes = self._reply("yes")

        prompted = user_prompt_with_hint(self.session, yes)

        self.assertIn(STEP_READY_HINT, prompted)
        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertTrue(prompted.startswith("yes"))

    def test_no_after_a_summary_gets_no_hint(self):
        self._replies(6)
        self._summary()
        no = self._reply("no, not quite")

        prompted = user_prompt_with_hint(self.session, no)

        self.assertIsNone(step_progress_hint(self.session, no))
        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
        self.assertNotIn("<TURN_HINT>", prompted)
        self.assertEqual(prompted, "no, not quite")

    def test_summary_hint_requires_the_summary_in_the_same_message(self):
        self._replies(5)
        Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="What else can you tell me about that worry?",
        )
        reply = self._reply()

        prompted = user_prompt_with_hint(self.session, reply)

        self.assertIn(STEP_SUMMARY_HINT, prompted)
        self.assertIn("In this same message", STEP_SUMMARY_HINT)
        self.assertIn("Do I have that right?", STEP_SUMMARY_HINT)
        self.assertIn("without the summary in the message", STEP_SUMMARY_HINT)
        self.assertTrue(prompted.startswith(reply.text))

    def test_yes_that_is_right_after_a_summary_asks_if_ready(self):
        self._replies(6)
        self._summary()
        yes = self._reply("Yes, that is right")

        prompted = user_prompt_with_hint(self.session, yes)

        self.assertIn(STEP_READY_HINT, prompted)
        self.assertNotIn(STEP_SUMMARY_HINT, prompted)
        self.assertTrue(prompted.startswith("Yes, that is right"))

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

        self.assertIn(STEP_SUMMARY_HINT, prompted)
        self.assertNotIn(STEP_READY_HINT, prompted)
        self.assertTrue(prompted.startswith(again.text))

    def _live_step(self):
        SessionStep.create(self.session, self.exercise)
        return self.session.session_steps.select_related("step").get(order=0).step

    def test_below_the_cap_does_not_check_done_when(self):
        self._live_step()
        replies = self._replies(5)
        with patch("api.utils.extraction.check_done_when") as checker:
            self.assertIsNone(step_progress_hint(self.session, replies[-1]))
        checker.assert_not_called()

    def test_at_the_cap_a_met_step_is_summarised(self):
        self._live_step()
        replies = self._replies(STEP_ANSWER_CAP)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": True, "missing": ""},
        ) as checker:
            self.assertEqual(step_progress_hint(self.session, replies[-1]), STEP_SUMMARY_HINT)
        checker.assert_called_once()

    def test_at_the_cap_a_substantive_gap_asks_one_question(self):
        self._live_step()
        replies = self._replies(STEP_ANSWER_CAP)
        missing = "what they would do about the obstacles"
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": missing},
        ):
            hint = step_progress_hint(self.session, replies[-1])
        self.assertEqual(hint, STEP_MISSING_HINT.format(missing=missing))
        self.assertIn(missing, hint)
        self.assertIn("ask exactly one question", hint)
        self.assertIn("build on what the user has already said", hint)
        self.assertIn("Ask nothing else, and do not summarise yet.", hint)
        self.assertNotIn(STEP_SUMMARY_HINT, hint)

    def test_a_missing_summary_confirmation_still_summarises(self):
        self._live_step()
        replies = self._replies(STEP_ANSWER_CAP)
        with patch(
            "api.utils.extraction.check_done_when",
            return_value={"met": False, "missing": "confirmed the summary is accurate"},
        ):
            self.assertEqual(step_progress_hint(self.session, replies[-1]), STEP_SUMMARY_HINT)

    def test_the_hard_cap_summarises_without_the_checker(self):
        self._live_step()
        replies = self._replies(STEP_HARD_CAP)
        with patch("api.utils.extraction.check_done_when") as checker:
            self.assertEqual(step_progress_hint(self.session, replies[-1]), STEP_SUMMARY_HINT)
        checker.assert_not_called()

    def test_a_failed_checker_still_summarises(self):
        self._live_step()
        replies = self._replies(STEP_ANSWER_CAP)
        with patch(
            "api.utils.extraction.check_done_when",
            side_effect=RuntimeError("down"),
        ):
            self.assertEqual(step_progress_hint(self.session, replies[-1]), STEP_SUMMARY_HINT)

    def test_a_confirmed_summary_is_not_asked_for_again(self):
        self._live_step()
        self._replies(4)
        self._summary()
        self._reply("yes")
        Message.objects.create(
            session=self.session,
            sender=self.agent,
            text="What else happens in that situation?",
        )
        again = self._reply("I fall behind on the bills")
        with patch("api.utils.extraction.check_done_when") as checker:
            self.assertIsNone(step_progress_hint(self.session, again))
        checker.assert_not_called()
