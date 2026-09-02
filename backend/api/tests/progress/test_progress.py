from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ..TestCase import TestCase
from ...exercise.models import Exercise
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...progress.models import UserObservation
from ...progress.services import generate_observation_for_consumer, get_streaks
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants, DateUtils


class ProgressApiTests(BaseTest):
    def endpoint(self):
        return "progress"

    def setUp(self):
        super().setUp()
        Setting.create_all()

        self.mood = KnowledgeField.objects.create(
            key="mood", label="Mood", category="Wellbeing", active=True
        )
        self.stress = KnowledgeField.objects.create(
            key="stress_points", label="Stress", category="Wellbeing", active=True
        )
        KnowledgeQuestion.objects.create(
            prompt="Mood?",
            target_field=self.mood,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
            value_labels=["Really low"] + [""] * 4 + ["Alright"] + [""] * 4 + ["Great"],
            flows=[Constants.KNOWLEDGE_FLOW_INITIAL, Constants.KNOWLEDGE_FLOW_RETURN],
            active=True,
        )

        self.consumer_one.date_of_birth = timezone.now().date().replace(year=1990)
        self.consumer_one.save(update_fields=["date_of_birth"])

    def _get_progress(self, path, query=None):
        return TestCase._get(
            path,
            query_params_dict=query or {},
            access_token=self.consumer_one_access_token,
        )

    def _add_mood(self, value: int, days_ago: int = 0):
        entry = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.mood,
            value=str(value),
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        if days_ago:
            KnowledgeEntry.objects.filter(id=entry.id).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )
        return entry

    def test_mood_empty_and_sparse(self):
        empty = self._get_progress("/progress/mood")
        self.assertEqual(empty.status_code, status.HTTP_200_OK, empty.json)
        self.assertTrue(empty.json["empty"])
        self.assertTrue(empty.json["sparse"])
        self.assertIsNone(empty.json["summary"])
        self.assertEqual(empty.json["check_in_dates"], [])

        self._add_mood(5)
        sparse = self._get_progress("/progress/mood")
        self.assertTrue(sparse.json["sparse"])
        self.assertEqual(sparse.json["summary"]["check_in_count"], 1)

        self._add_mood(7, days_ago=1)
        ok = self._get_progress("/progress/mood")
        self.assertFalse(ok.json["sparse"])
        self.assertEqual(len(ok.json["points"]), 2)
        self.assertIn(ok.json["points"][-1]["label"], ("Alright", "Great", ""))

    def test_check_in_without_mood_slider(self):
        other = KnowledgeField.objects.create(
            key="sleep", label="Sleep", category="Wellbeing", active=True
        )
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=other,
            value="restless",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        mood = self._get_progress("/progress/mood")
        self.assertFalse(mood.json["empty"])
        self.assertEqual(mood.json["summary"]["check_in_count"], 1)
        self.assertEqual(mood.json["points"], [])
        self.assertEqual(len(mood.json["check_in_dates"]), 1)
        streaks = self._get_progress("/progress/streaks")
        self.assertEqual(streaks.json["check_in"]["current"], 1)

    def test_mood_from_second_slider_when_named_field_unused(self):
        KnowledgeQuestion.objects.filter(target_field=self.mood).delete()
        energy = KnowledgeField.objects.create(
            key="energy", label="Energy", category="Wellbeing", active=True
        )
        feeling = KnowledgeField.objects.create(
            key="how_im_feeling", label="Feeling", category="Wellbeing", active=True
        )
        KnowledgeQuestion.objects.create(
            prompt="Energy today?",
            target_field=energy,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
            flows=[Constants.KNOWLEDGE_FLOW_RETURN, Constants.KNOWLEDGE_FLOW_INITIAL],
            order=1,
            active=True,
        )
        KnowledgeQuestion.objects.create(
            prompt="How are you feeling?",
            target_field=feeling,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
            flows=[Constants.KNOWLEDGE_FLOW_RETURN, Constants.KNOWLEDGE_FLOW_INITIAL],
            order=2,
            active=True,
        )
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=energy,
            value="0",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=feeling,
            value="10",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        mood = self._get_progress("/progress/mood")
        self.assertEqual(mood.status_code, status.HTTP_200_OK, mood.json)
        self.assertEqual(len(mood.json["points"]), 1)
        self.assertEqual(mood.json["points"][0]["value"], 10)
        self.assertEqual(mood.json["points"][0]["value_scaled"], 100)

    def test_mood_gaps_not_zeros(self):
        self._add_mood(4, days_ago=3)
        self._add_mood(6, days_ago=0)
        today = DateUtils.progress_calendar_date()
        response = self._get_progress(
            "/progress/mood",
            {
                "from": (today - timedelta(days=3)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dates = [p["date"] for p in response.json["points"]]
        self.assertEqual(len(dates), 2)
        self.assertNotIn((today - timedelta(days=1)).isoformat(), dates)

    def test_exercises_heatmap_and_breakdown(self):
        exercise = General.create_exercise()
        today = DateUtils.progress_calendar_date()
        for days_ago in (0, 0, 2):
            session = Session.objects.create(
                consumer=self.consumer_one,
                exercise=exercise,
                completed=True,
                current_step_no=exercise.steps_no,
                total_steps_no=exercise.steps_no,
            )
            when = timezone.now() - timedelta(days=days_ago)
            Session.objects.filter(id=session.id).update(
                created_at=when,
                completed_at=when,
                updated_at=when,
            )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (today - timedelta(days=3)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["total_completions"], 3)
        self.assertEqual(len(response.json["breakdown"]), 1)
        self.assertEqual(response.json["breakdown"][0]["completions"], 3)
        completed_days = sum(1 for cell in response.json["heatmap"] if cell["completed"])
        self.assertEqual(completed_days, 2)
        today_cell = next(cell for cell in response.json["heatmap"] if cell["date"] == today.isoformat())
        self.assertGreater(today_cell["minutes"], 0)

    def test_exercises_heatmap_uses_actual_minutes_not_catalogue(self):
        exercise = General.create_exercise()
        Exercise.objects.filter(id=exercise.id).update(average_duration=1800)
        today = DateUtils.progress_calendar_date()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        started = timezone.now() - timedelta(minutes=8)
        Session.objects.filter(id=session.id).update(
            created_at=started,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (today - timedelta(days=1)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        today_cell = next(cell for cell in response.json["heatmap"] if cell["date"] == today.isoformat())
        self.assertEqual(today_cell["minutes"], 8)

    def test_exercises_heatmap_ignores_idle_pause_gaps(self):
        from ...message.models import Message
        from ...participant.models import Participant

        exercise = General.create_exercise()
        today = DateUtils.progress_calendar_date()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        consumer_pt, agent_pt = Participant.create_participants(session)
        started = timezone.now() - timedelta(days=2)
        active_start = timezone.now() - timedelta(minutes=8)
        finished = timezone.now()
        first = Message.objects.create(session=session, sender=consumer_pt, text="start")
        last = Message.objects.create(session=session, sender=agent_pt, text="done")
        Message.objects.filter(id=first.id).update(created_at=active_start)
        Message.objects.filter(id=last.id).update(created_at=finished)
        Session.objects.filter(id=session.id).update(
            created_at=started,
            completed_at=finished,
            updated_at=finished,
            last_message_id=last.id,
        )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (today - timedelta(days=3)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        today_cell = next(cell for cell in response.json["heatmap"] if cell["date"] == today.isoformat())
        self.assertEqual(today_cell["minutes"], 8)
        self.assertLess(today_cell["minutes"], Constants.PROGRESS_ACTIVITY_MAX_MINUTES)

    def test_exercises_heatmap_does_not_use_catalogue_when_elapsed_is_missing(self):
        exercise = General.create_exercise()
        Exercise.objects.filter(id=exercise.id).update(average_duration=1800)
        today = DateUtils.progress_calendar_date()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        when = timezone.now()
        Session.objects.filter(id=session.id).update(
            created_at=when,
            completed_at=when,
            updated_at=when,
        )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (today - timedelta(days=1)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        today_cell = next(cell for cell in response.json["heatmap"] if cell["date"] == today.isoformat())
        self.assertEqual(today_cell["minutes"], 1)
        self.assertNotEqual(today_cell["minutes"], 30)

    def test_exercises_heatmap_uses_completed_at_not_created_at(self):
        exercise = General.create_exercise()
        today = DateUtils.progress_calendar_date()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        started = timezone.now() - timedelta(days=2)
        Session.objects.filter(id=session.id).update(
            created_at=started,
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (today - timedelta(days=3)).isoformat(),
                "to": today.isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        by_date = {cell["date"]: cell for cell in response.json["heatmap"]}
        self.assertTrue(by_date[today.isoformat()]["completed"])
        self.assertFalse(by_date[(today - timedelta(days=2)).isoformat()]["completed"])

    def test_exercises_heatmap_buckets_ireland_calendar_day(self):
        exercise = General.create_exercise()
        dublin = ZoneInfo("Europe/Dublin")
        started = datetime(2026, 8, 29, 12, 0, tzinfo=dublin)
        completed = datetime(2026, 8, 31, 0, 30, tzinfo=dublin)
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=exercise.steps_no,
            total_steps_no=exercise.steps_no,
        )
        Session.objects.filter(id=session.id).update(
            created_at=started,
            completed_at=completed,
            updated_at=completed,
        )

        response = self._get_progress(
            "/progress/exercises",
            {"from": "2026-08-29", "to": "2026-08-31"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        by_date = {cell["date"]: cell for cell in response.json["heatmap"]}
        self.assertTrue(by_date["2026-08-31"]["completed"])
        self.assertFalse(by_date["2026-08-30"]["completed"])
        self.assertFalse(by_date["2026-08-29"]["completed"])

    def test_patterns_stress_and_observation(self):
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.stress,
            value="Work,Family",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.stress,
            value="Work",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )
        UserObservation.objects.create(
            consumer=self.consumer_one,
            text="We noticed work comes up often for you.",
            topic_tag="work anxiety",
            generated_at=timezone.now(),
        )

        response = self._get_progress("/progress/patterns")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertTrue(response.json["observations_enabled"])
        self.assertEqual(response.json["observation"]["topic_tag"], "work anxiety")
        categories = {row["category"]: row["count"] for row in response.json["stress_points"]}
        self.assertEqual(categories["Work"], 2)
        self.assertEqual(categories["Family"], 1)

    def test_patterns_hides_observation_when_disabled(self):
        setting = Setting.get_or_create_observations_enabled()
        setting.value = "false"
        setting.save()
        UserObservation.objects.create(
            consumer=self.consumer_one,
            text="Hidden",
            topic_tag="x",
            generated_at=timezone.now(),
        )
        response = self._get_progress("/progress/patterns")
        self.assertIsNone(response.json["observation"])
        self.assertFalse(response.json["observations_enabled"])

    def test_streaks(self):
        self._add_mood(5, days_ago=0)
        self._add_mood(6, days_ago=1)
        self._add_mood(4, days_ago=2)

        exercise = General.create_exercise()
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            current_step_no=1,
            total_steps_no=1,
        )
        Session.objects.filter(id=session.id).update(
            created_at=timezone.now(),
            completed_at=timezone.now(),
            updated_at=timezone.now(),
        )

        response = self._get_progress("/progress/streaks")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["check_in"]["current"], 3)
        self.assertGreaterEqual(response.json["check_in"]["best"], 3)
        self.assertEqual(response.json["exercise"]["current"], 1)

    def test_observation_task_retains_prior_on_failure(self):
        prior = UserObservation.objects.create(
            consumer=self.consumer_one,
            text="Prior observation",
            topic_tag="prior",
            generated_at=timezone.now() - timedelta(hours=25),
        )
        with mock.patch(
            "api.progress.services._run_observation_ai",
            side_effect=RuntimeError("boom"),
        ):
            result = generate_observation_for_consumer(self.consumer_one)
        self.assertEqual(result.id, prior.id)
        self.assertEqual(
            UserObservation.objects.filter(consumer=self.consumer_one).count(), 1
        )

    def test_observation_task_creates_when_due(self):
        with mock.patch("api.progress.services._run_observation_ai") as run:
            run.return_value = type(
                "R", (), {"text": "You often mention sleep.", "topic_tag": "sleep"}
            )()
            created = generate_observation_for_consumer(self.consumer_one)
        self.assertIsNotNone(created)
        self.assertEqual(created.topic_tag, "sleep")
        self.assertEqual(get_streaks(self.consumer_one)["check_in"]["current"], 0)
