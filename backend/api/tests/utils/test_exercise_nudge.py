from django.core.cache import cache
from django.utils import timezone

from ...exercise.models import Exercise
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...setting.models import Setting
from ...summary.models import Summary
from ...utils import Constants
from ...utils.ExerciseOffer import OFFER_DECLINE_HINT_KEY, offer_decline_hint
from ...utils.turn_hint import EXERCISE_NUDGE_HINT, user_prompt_with_hint
from ..TestCase import TestCase
from ..utils.manager import Auth


class ExerciseNudgeHintTests(TestCase):
    def _open(self, **session_kwargs):
        consumer = Auth.create_consumer()
        session = Session.objects.create(consumer=consumer, **session_kwargs)
        user, agent = Participant.create_participants(session)
        return session, user, agent

    def _say(self, session, user, text="I've been worried about work"):
        return Message.objects.create(session=session, sender=user, text=text)

    def test_nudge_starts_on_the_third_person_message_and_is_logged(self):
        session, user, _agent = self._open()
        first = self._say(session, user, "hello")
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(session, first))
        second = self._say(session, user, "I'm a bit stressed")
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(session, second))

        third = self._say(session, user, "I've been worried about losing my job")
        with self.assertLogs("api.utils.turn_hint", level="INFO") as logs:
            prompted = user_prompt_with_hint(session, third)
        self.assertIn(EXERCISE_NUDGE_HINT, prompted)
        self.assertTrue(prompted.strip().endswith("</TURN_HINT>"))
        line = logs.output[0]
        self.assertIn(
            f"general-chat exercise nudge session={session.id} message={third.id} count=1",
            line,
        )
        self.assertNotIn("losing my job", line)
        session.refresh_from_db()
        self.assertEqual(session.cached_prompt_meta["exercise_nudges_sent"], 1)
        self.assertEqual(session.cached_prompt_meta["exercise_nudge_last_at"], 3)

    def test_second_nudge_waits_for_three_more_messages_and_stops(self):
        session, user, _agent = self._open()
        for number in range(1, 10):
            message = self._say(session, user, f"message {number}")
            prompted = user_prompt_with_hint(session, message)
            session.refresh_from_db()
            sent = (session.cached_prompt_meta or {}).get("exercise_nudges_sent")
            if number in (1, 2, 4, 5, 7, 8, 9):
                self.assertNotIn(EXERCISE_NUDGE_HINT, prompted, number)
            else:
                self.assertIn(EXERCISE_NUDGE_HINT, prompted, number)
            if number < 3:
                self.assertIsNone(sent)
            elif number < 6:
                self.assertEqual(sent, 1)
            else:
                self.assertEqual(sent, 2)

    def test_no_nudge_after_an_offer_or_a_decline(self):
        offered, user, _agent = self._open()
        offered.cached_prompt_meta = {
            "exercise_offers": [
                {
                    "exercise_id": "exr_old",
                    "title": "Stay Present",
                    "outcome": "offered",
                    "at_consumer_messages_no": 0,
                }
            ]
        }
        offered.save(update_fields=["cached_prompt_meta", "updated_at"])
        for _ in range(8):
            self._say(offered, user, "still talking")
        ninth = self._say(offered, user, "and this is much later")
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(offered, ninth))

        declined, declined_user, _agent = self._open()
        declined.cached_prompt_meta = {
            "exercise_offers": [
                {
                    "exercise_id": "exr_old",
                    "title": "Stay Present",
                    "outcome": "declined",
                    "at_consumer_messages_no": 1,
                }
            ]
        }
        declined.save(update_fields=["cached_prompt_meta", "updated_at"])
        self._say(declined, declined_user)
        self._say(declined, declined_user)
        third = self._say(declined, declined_user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(declined, third))

    def test_a_matched_exercise_message_counts_as_an_offer(self):
        session, user, agent = self._open()
        exercise = Exercise.objects.create(
            title="Stay Present",
            subtitle="Stay",
            description="Stay",
            steps_no=1,
            icon="leaf",
            icon_background_color="tan",
            status=Constants.EXERCISE_STATUS_PUBLISHED,
        )
        Message.objects.create(
            session=session,
            sender=agent,
            text="Would you like to try Stay Present?",
            exercise=exercise,
        )
        self._say(session, user)
        self._say(session, user)
        third = self._say(session, user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(session, third))

    def test_tapped_no_and_about_the_user_win_and_are_not_counted(self):
        session, user, _agent = self._open()
        self._say(session, user)
        self._say(session, user)
        session.cached_prompt_meta = {
            OFFER_DECLINE_HINT_KEY: offer_decline_hint("Stay Present"),
        }
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        tapped = self._say(session, user, "No")
        prompted = user_prompt_with_hint(session, tapped)
        self.assertIn("declined the offered exercise", prompted)
        self.assertNotIn(EXERCISE_NUDGE_HINT, prompted)
        session.refresh_from_db()
        self.assertNotIn("exercise_nudges_sent", session.cached_prompt_meta or {})

        consumer = Auth.create_consumer()
        summary = Summary.get_or_create(consumer)
        summary.detailed = "Worries about work presentations."
        summary.save(update_fields=["detailed", "updated_at"])
        about_session = Session.objects.create(consumer=consumer)
        about_user, _about_agent = Participant.create_participants(about_session)
        self._say(about_session, about_user, "hello")
        self._say(about_session, about_user, "I'm stressed")
        asking = self._say(about_session, about_user, "what do you know about me?")
        prompted = user_prompt_with_hint(about_session, asking)
        self.assertIn("is asking what you know about them", prompted)
        self.assertNotIn(EXERCISE_NUDGE_HINT, prompted)
        about_session.refresh_from_db()
        self.assertNotIn("exercise_nudges_sent", about_session.cached_prompt_meta or {})

    def test_no_nudge_when_risk_is_moderate_or_high_or_the_session_is_closed(self):
        moderate, user, _agent = self._open(live_risk_level=Constants.LIVE_RISK_LEVEL_MODERATE)
        self._say(moderate, user)
        self._say(moderate, user)
        third = self._say(moderate, user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(moderate, third))

        high, high_user, _agent = self._open(live_risk_level=Constants.LIVE_RISK_LEVEL_HIGH)
        self._say(high, high_user)
        self._say(high, high_user)
        third = self._say(high, high_user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(high, third))

        flagged, flagged_user, _agent = self._open()
        self._say(flagged, flagged_user, "hello")
        self._say(flagged, flagged_user, "I'm stressed")
        crisis = self._say(flagged, flagged_user, "I might hurt myself")
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(flagged, crisis))

        closed, closed_user, _agent = self._open(closed_at=timezone.now())
        self._say(closed, closed_user)
        self._say(closed, closed_user)
        third = self._say(closed, closed_user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(closed, third))

    def test_no_nudge_in_an_exercise_session(self):
        consumer = Auth.create_consumer()
        exercise = Exercise.objects.create(
            title="Hint exercise",
            subtitle="Hint",
            description="Hint",
            steps_no=1,
            icon="leaf",
            icon_background_color="tan",
            status=Constants.EXERCISE_STATUS_PUBLISHED,
        )
        session = Session.objects.create(consumer=consumer, exercise=exercise)
        user, _agent = Participant.create_participants(session)
        self._say(session, user)
        self._say(session, user)
        third = self._say(session, user)
        self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(session, third))

    def test_setting_off_means_never(self):
        row = Setting.get_or_create_exercise_nudge_enabled()
        row.value = "false"
        row.save()
        cache.delete("setting:value:exercise_nudge_enabled")
        try:
            session, user, _agent = self._open()
            self._say(session, user)
            self._say(session, user)
            third = self._say(session, user)
            self.assertNotIn(EXERCISE_NUDGE_HINT, user_prompt_with_hint(session, third))
            session.refresh_from_db()
            self.assertNotIn("exercise_nudges_sent", session.cached_prompt_meta or {})
        finally:
            row.value = "true"
            row.save()
            cache.delete("setting:value:exercise_nudge_enabled")
