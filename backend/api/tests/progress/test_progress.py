from datetime import timedelta
from unittest import mock

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
from ...utils import Constants


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

        self._add_mood(5)
        sparse = self._get_progress("/progress/mood")
        self.assertTrue(sparse.json["sparse"])
        self.assertEqual(sparse.json["summary"]["check_in_count"], 1)

        self._add_mood(7, days_ago=1)
        ok = self._get_progress("/progress/mood")
        self.assertFalse(ok.json["sparse"])
        self.assertEqual(len(ok.json["points"]), 2)
        self.assertIn(ok.json["points"][-1]["label"], ("Alright", "Great", ""))

    def test_mood_gaps_not_zeros(self):
        self._add_mood(4, days_ago=3)
        self._add_mood(6, days_ago=0)
        response = self._get_progress(
            "/progress/mood",
            {
                "from": (timezone.localdate() - timedelta(days=3)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dates = [p["date"] for p in response.json["points"]]
        self.assertEqual(len(dates), 2)
        self.assertNotIn(
            (timezone.localdate() - timedelta(days=1)).isoformat(), dates
        )

    def test_exercises_heatmap_and_breakdown(self):
        exercise = General.create_exercise()
        for days_ago in (0, 0, 2):
            session = Session.objects.create(
                consumer=self.consumer_one,
                exercise=exercise,
                completed=True,
                current_step_no=exercise.steps_no,
                total_steps_no=exercise.steps_no,
            )
            Session.objects.filter(id=session.id).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )

        response = self._get_progress(
            "/progress/exercises",
            {
                "from": (timezone.localdate() - timedelta(days=3)).isoformat(),
                "to": timezone.localdate().isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["total_completions"], 3)
        self.assertEqual(len(response.json["breakdown"]), 1)
        self.assertEqual(response.json["breakdown"][0]["completions"], 3)
        completed_days = sum(1 for cell in response.json["heatmap"] if cell["completed"])
        self.assertEqual(completed_days, 2)

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
        Session.objects.filter(id=session.id).update(created_at=timezone.now())

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
