import importlib
from unittest.mock import patch

from django.apps import apps
from django.db import connection
from django.utils import timezone
from rest_framework import status

from ...participant.models import Participant
from ...run.services import completed_runs_queryset
from ...session.models import Session
from ...tests.TestCase import TestCase
from ...utils.Agent import _prepare_prompt
from ...utils.session_close import close_session
from ..utils.manager import Auth, General


class CreateTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.access_token = Auth.get_access_token(self.consumer.user)
        self.admin = Auth.create_admin()
        self.admin_access_token = Auth.get_access_token(self.admin.user)

    def test_creates_fresh_general_session(self):
        existing = General.create_session(consumer=self.consumer)

        response = self._post("/sessions", {}, access_token=self.access_token)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(response.json["id"], existing.id)
        self.assertIsNone(response.json["exercise"])
        self.assertIsNone(response.json["last_message"])
        self.assertEqual(response.json["phase"], "general")

        session = Session.objects.get(id=response.json["id"])
        self.assertEqual(session.consumer_id, self.consumer.user_id)
        self.assertIsNone(session.exercise_id)
        self.assertIsNone(session.source_run_id)
        self.assertFalse(session.authoring_test)
        self.assertEqual(
            Participant.objects.filter(session=session).count(),
            2,
        )

    def test_authoring_test_migration_tolerates_existing_column(self):
        migration = importlib.import_module(
            "api.migrations.0080_session_authoring_test"
        )
        with connection.schema_editor() as schema_editor:
            migration.add_authoring_test(apps, schema_editor)

        session = Session.objects.create(consumer=self.consumer)
        self.assertFalse(session.authoring_test)

    def test_second_post_creates_another_session(self):
        first = self._post("/sessions", {}, access_token=self.access_token)
        second = self._post("/sessions", {}, access_token=self.access_token)

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(first.json["id"], second.json["id"])
        self.assertEqual(
            Session.objects.filter(consumer=self.consumer, exercise__isnull=True).count(),
            2,
        )

    def test_admin_cannot_create(self):
        response = self._post("/sessions", {}, access_token=self.admin_access_token)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_cannot_create(self):
        response = self._post("/sessions", {})
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def _completed_run(self, consumer, summary):
        exercise = General.create_exercise()
        run = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            completed=True,
            completed_at=timezone.now(),
            current_step_no=1,
            total_steps_no=exercise.steps_no or 1,
            run_summary=summary,
        )
        return run, exercise

    def test_run_id_links_a_general_chat_to_the_completed_run(self):
        summary = {"line": "You stayed with it", "bullets": ["The worry shrank"]}
        run, exercise = self._completed_run(self.consumer, summary)

        response = self._post(
            "/sessions",
            {"runId": run.id},
            access_token=self.access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.assertEqual(response.json["source_run"], run.id)
        self.assertIsNone(response.json["exercise"])
        self.assertEqual(response.json["phase"], "general")
        chat = Session.objects.get(id=response.json["id"])
        self.assertEqual(chat.source_run_id, run.id)
        self.assertIsNone(chat.exercise_id)
        self.assertIsNone(chat.run_summary)
        self.assertNotEqual(chat.completed, True)
        completions = exercise.completions_no
        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, completions)

        listed = set(completed_runs_queryset(self.consumer).values_list("id", flat=True))
        self.assertIn(run.id, listed)
        self.assertNotIn(chat.id, listed)

        chat.completed = True
        chat.save(update_fields=["completed", "updated_at"])
        with (
            patch("api.utils.session_close._rate"),
            patch("api.utils.session_close._extract_pending_question"),
            patch("api.utils.AI.AI.ask") as ask,
        ):
            close_session(chat, "completed")
        chat.refresh_from_db()
        run.refresh_from_db()
        self.assertIsNone(chat.run_summary)
        self.assertIsNone(chat.exercise_id)
        self.assertEqual(run.run_summary, summary)
        ask.assert_not_called()
        listed = set(completed_runs_queryset(self.consumer).values_list("id", flat=True))
        self.assertNotIn(chat.id, listed)

    def test_another_users_run_id_is_not_found(self):
        other = Auth.create_consumer()
        run, _exercise = self._completed_run(
            other,
            {"line": "Private", "bullets": ["Hidden"]},
        )
        before = Session.objects.filter(consumer=self.consumer).count()

        response = self._post(
            "/sessions",
            {"runId": run.id},
            access_token=self.access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json, {"detail": "Not found."})
        self.assertNotIn(run.id, response.content.decode())
        self.assertEqual(Session.objects.filter(consumer=self.consumer).count(), before)

    def test_prompt_includes_the_run_only_when_it_has_a_summary(self):
        bare_run, _bare_exercise = self._completed_run(self.consumer, None)
        bare_chat = Session.create_general(self.consumer)
        bare_chat.source_run = bare_run
        bare_chat.save(update_fields=["source_run", "updated_at"])
        without = _prepare_prompt(bare_chat)
        self.assertNotIn("It is not something the user said.", without)
        self.assertNotIn("what they want to reflect on", without)

        plain = Session.create_general(self.consumer)
        self.assertNotIn("It is not something the user said.", _prepare_prompt(plain))

        run, exercise = self._completed_run(self.consumer, None)
        chat = Session.create_general(self.consumer)
        chat.source_run = run
        chat.save(update_fields=["source_run", "updated_at"])
        before = _prepare_prompt(chat)
        self.assertNotIn("You stayed with it", before)

        run.run_summary = {"line": "You stayed with it", "bullets": ["The worry shrank"]}
        run.save(update_fields=["run_summary", "updated_at"])
        chat = Session.objects.get(id=chat.id)
        after = _prepare_prompt(chat)
        self.assertIn(exercise.title, after)
        self.assertIn("You stayed with it", after)
        self.assertIn("- The worry shrank", after)
        self.assertIn("It is not something the user said.", after)
        self.assertIn(
            "If the user has not said what they want to reflect on, ask them. Otherwise follow the conversation.",
            after,
        )
        self.assertIsNone(chat.exercise_id)
        chat.refresh_from_db()
        self.assertIsNone(chat.run_summary)
        self.assertIn("You stayed with it", _prepare_prompt(chat))
