import importlib

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from api.agent.models import Agent
from api.consumer.models import Consumer
from api.exercise.models import Exercise
from api.image.models import Image

_wp1 = importlib.import_module("api.migrations.0070_wp1_additive_schema")
backfill_check_in = _wp1.backfill_check_in
backfill_question_keys = _wp1.backfill_question_keys
backfill_session_state = _wp1.backfill_session_state
backfill_steps = _wp1.backfill_steps
seed_prompt_versions = _wp1.seed_prompt_versions
from api.prompt.models import PromptVersion
from api.question.models import Question
from api.session.models import Session
from api.session.serializers import SessionListSerializer
from api.step.models import Step
from api.step.serializers import StepCreateSerializer
from api.user.models import User
from api.utils import Constants


class WP1AdditiveSchemaTests(TestCase):
    def test_prompt_versions_seeded_from_current_settings(self):
        seed_prompt_versions(apps, None)

        rows = {
            row.key: row
            for row in PromptVersion.objects.filter(version=1, active=True)
        }
        self.assertEqual(
            set(rows),
            {
                Constants.PROMPT_KEY_THERAPEUTIC,
                Constants.PROMPT_KEY_GOALS,
                Constants.PROMPT_KEY_OBSERVATIONS_INSTRUCTION,
                Constants.PROMPT_KEY_OBSERVATIONS_TONE_GUIDE,
            },
        )
        for row in rows.values():
            self.assertTrue(row.body)

    def test_backfill_copies_check_in_steps_questions_and_session_state(self):
        exercise = Exercise.objects.create(
            title="Overcome Worry",
            subtitle="A plan for a worry",
            description="Work through one worry.",
            status=Constants.EXERCISE_STATUS_DRAFT,
            steps_no=2,
            icon="leaf",
            icon_background_color="tan",
            pre_exercise_enabled=False,
            pre_exercise_description="Warm tone",
            pre_exercise_instruction="Ask how the last plan went.",
            pre_exercise_goal="Hear how it went.",
            pre_exercise_completion_prompt="Summarise the check-in.",
            pre_exercise_start_button_label="Begin",
        )
        Step.objects.create(
            exercise=exercise,
            title="Name the Worry",
            description="Name it",
            instructions="Ask them to name it",
            completion_criteria="A specific worry",
            completion_label="Your worry",
            completion_prompt="State the worry.",
            order=0,
        )
        Step.objects.create(
            exercise=exercise,
            title="Name the Worry",
            description="Name it again",
            instructions="Ask again",
            completion_criteria="Another worry",
            completion_label="Your other worry",
            completion_prompt="State the other worry.",
            order=1,
        )
        Question.objects.create(
            exercise=exercise,
            type=Constants.QUESTION_TYPE_NUMBER,
            title="How disruptive?",
            order=0,
        )

        backfill_check_in(apps, None)
        backfill_steps(apps, None)
        backfill_question_keys(apps, None)

        exercise.refresh_from_db()
        self.assertFalse(exercise.check_in_enabled)
        self.assertEqual(exercise.check_in_tone, "Warm tone")
        self.assertEqual(exercise.check_in_instruction, "Ask how the last plan went.")
        self.assertEqual(exercise.check_in_goal, "Hear how it went.")
        self.assertEqual(exercise.check_in_summary_prompt, "Summarise the check-in.")
        self.assertEqual(exercise.check_in_start_button_label, "Begin")

        keys = set(exercise.steps.order_by("order").values_list("key", flat=True))
        self.assertEqual(keys, {"name-the-worry", "name-the-worry-2"})
        self.assertEqual(
            set(exercise.steps.values_list("done_when", flat=True)),
            {"A specific worry", "Another worry"},
        )
        self.assertEqual(exercise.questions.get().key, "how-disruptive")

        user = User.objects.create(
            email="wp1-schema@example.com",
            type=Constants.USER_TYPE_CONSUMER,
            first_name="WP",
            last_name="One",
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
        consumer = Consumer.objects.create(user=user, agent=agent)
        general = Session.objects.create(consumer=consumer)
        in_progress = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            completed=False,
            current_step_no=0,
        )
        finished = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            completed=True,
            completed_at=timezone.now(),
        )

        backfill_session_state(apps, None)

        general.refresh_from_db()
        in_progress.refresh_from_db()
        finished.refresh_from_db()
        self.assertEqual(general.state, Constants.SESSION_STATE_GENERAL)
        self.assertEqual(in_progress.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(finished.state, Constants.SESSION_STATE_COMPLETED)

    def test_new_session_fields_stay_off_the_api_and_completion_prompt_stays_required(self):
        hidden = {
            "state",
            "closed_at",
            "form_answers",
            "prompt_version",
            "live_risk_level",
            "cached_prompt_meta",
        }
        self.assertTrue(hidden <= set(SessionListSerializer.Meta.exclude))

        serializer = StepCreateSerializer(data={"title": "Breathe"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("completion_prompt", serializer.errors)
