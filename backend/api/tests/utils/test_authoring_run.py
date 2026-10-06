"""A finished exercise-builder test run stays on its own session."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from ...exercise.models import Exercise
from ...tag.models import Tag
from ...exercise.pre_exercise import has_completed_exercise_before
from ...exercise_summary.models import ExerciseSummary
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ...message.models import Message
from ...participant.models import Participant
from ...progress.services import (
    _recent_transcript_excerpt,
    get_exercises_progress,
    get_streaks,
)
from ...question.models import Question
from ...run.services import completed_runs_queryset
from ...session.models import Session, SessionMetric, SessionStep
from ...setting.models import Setting
from ...step.models import Step
from ...summary.models import Summary
from ...utils import Constants, DateUtils
from ...utils.Agent import ExerciseStateResponse, _prepare_prompt
from ...utils.authoring_run import (
    AuthoringDeleteRefused,
    delete_authoring_run,
    sweep_authoring_test_runs,
    write_authoring_snapshot,
)
from ...utils.form_answers import record_onboarding_knowledge, save_form_answer
from ...utils.prompt_blocks import render_session_context
from ...utils.risk import apply_turn_risk
from ...utils.SessionStateMachine import _confirm, opening_turn
from ...utils.session_close import close_idle_sessions
from ..TestCase import TestCase
from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ..utils.manager.Auth import create_admin, get_access_token


def _ai_payload(*_args, **_kwargs):
    return {
        "value": "the worry about work",
        "confidence": 0.95,
        "met": True,
        "missing": "",
        "detailed": "rewritten notes",
        "observations": "rewritten observations",
        "next_steps": "rewritten next steps",
        "subject": "Test subject",
        "rating": 8,
        "rating_reason": "rewritten",
        "risk_level": "low",
        "text": "rewritten",
    }


class AuthoringRunIsolationTests(BaseTest):
    def endpoint(self):
        return "sessions"

    def _finished_flagged_run(self):
        exercise = General.create_exercise()
        exercise.completions_no = 4
        exercise.save(update_fields=["completions_no"])
        step = exercise.steps.order_by("order").first()
        result_field = KnowledgeField.objects.create(
            key=f"worry_{exercise.id}",
            label="Worry",
            category="Worry",
            active=True,
        )
        close_field = KnowledgeField.objects.create(
            key=f"close_{exercise.id}",
            label="Close",
            category="Worry",
            active=True,
        )
        step.completion_prompt = "Name the worry."
        step.result_field = result_field
        step.save(update_fields=["completion_prompt", "result_field", "updated_at"])
        pending = KnowledgeQuestion.objects.create(
            prompt="Anything else?",
            target_field=close_field,
            extraction_prompt="Extract the leftover answer.",
            active=True,
        )
        notes = ExerciseSummary.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            detailed="original notes",
            observations="original observations",
            next_steps="original next steps",
        )
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=True,
            completed=False,
            current_step_no=(step.order or 0) + 1,
            total_steps_no=exercise.steps_no,
            state=Constants.SESSION_STATE_AWAITING_READY,
            pending_knowledge_question=pending,
        )
        from ...session.models import SessionStep

        SessionStep.create(session, exercise)
        consumer_participant, agent_participant = Participant.create_participants(session)
        Message.objects.create(
            session=session,
            sender=agent_participant,
            text="Are you ready to finish?",
        )
        user_message = Message.objects.create(
            session=session,
            sender=consumer_participant,
            text="Finish exercise",
        )
        form_question = Question.objects.create(
            session=session,
            type=Constants.QUESTION_TYPE_TEXT,
            title="What should we remember?",
            key="remember",
            attribute_key="remember",
            knowledge_field=close_field,
        )
        return exercise, notes, session, user_message, form_question

    def test_finished_flagged_run_does_not_escape(self):
        exercise, notes, session, user_message, form_question = self._finished_flagged_run()
        knowledge_before = KnowledgeEntry.objects.filter(consumer=self.consumer_one).count()
        metrics_before = SessionMetric.objects.filter(consumer=self.consumer_one).count()
        summary_before = list(
            Summary.objects.filter(consumer=self.consumer_one).values(
                "detailed", "observations", "next_steps"
            )
        )
        exercise_summaries = ExerciseSummary.objects.filter(
            consumer=self.consumer_one, exercise=exercise
        ).count()

        save_form_answer(session, "disruptiveness", "4")
        record_onboarding_knowledge(
            SimpleNamespace(
                question=form_question,
                value="remember this",
                consumer=self.consumer_one,
            )
        )
        with patch("api.tasks.notify_trust_and_safety.delay_on_commit") as queued:
            apply_turn_risk(session, "I want to die", "low")
        queued.assert_not_called()

        with patch("api.utils.AI.AI.ask", side_effect=_ai_payload):
            _confirm(session, user_message, finishing=True)

        exercise.refresh_from_db()
        notes.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)
        self.assertEqual(
            KnowledgeEntry.objects.filter(consumer=self.consumer_one).count(),
            knowledge_before,
        )
        self.assertEqual(
            SessionMetric.objects.filter(consumer=self.consumer_one).count(),
            metrics_before,
        )
        self.assertEqual(
            ExerciseSummary.objects.filter(
                consumer=self.consumer_one, exercise=exercise
            ).count(),
            exercise_summaries,
        )
        self.assertEqual(notes.detailed, "original notes")
        self.assertEqual(notes.observations, "original observations")
        self.assertEqual(notes.next_steps, "original next steps")
        self.assertEqual(
            list(
                Summary.objects.filter(consumer=self.consumer_one).values(
                    "detailed", "observations", "next_steps"
                )
            ),
            summary_before,
        )
        self.assertTrue(session.completed)
        self.assertEqual(session.live_risk_level, Constants.LIVE_RISK_LEVEL_HIGH)
        self.assertEqual(session.form_answers["disruptiveness"], "4")

    def test_unflagged_finish_still_counts_a_completion(self):
        exercise, _notes, session, user_message, _question = self._finished_flagged_run()
        session.authoring_test = False
        session.save(update_fields=["authoring_test", "updated_at"])

        with patch("api.utils.AI.AI.ask", side_effect=_ai_payload):
            _confirm(session, user_message, finishing=True)

        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, 5)

    def test_flagged_sessions_stay_out_of_history_reflect_and_progress(self):
        exercise = General.create_exercise()
        exercise.title = "Real run exercise"
        exercise.save(update_fields=["title", "updated_at"])
        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            completed=True,
            abandoned=False,
            current_step_no=1,
            total_steps_no=1,
            subject="Real subject",
        )
        when = timezone.now()
        Session.objects.filter(id=real.id).update(
            completed_at=when, updated_at=when, created_at=when
        )
        real.refresh_from_db()
        consumer_participant, agent_participant = Participant.create_participants(real)
        Message.objects.create(
            session=real, sender=consumer_participant, text="a real reply"
        )

        hidden_exercise = General.create_exercise()
        hidden_exercise.title = "Hidden test exercise"
        hidden_exercise.save(update_fields=["title", "updated_at"])
        hidden = Session.objects.create(
            consumer=self.consumer_one,
            exercise=hidden_exercise,
            authoring_test=True,
            completed=True,
            abandoned=False,
            current_step_no=1,
            total_steps_no=1,
            subject="Hidden subject",
        )
        Session.objects.filter(id=hidden.id).update(
            completed_at=when, updated_at=when, created_at=when
        )
        hidden.refresh_from_db()
        hidden_user, _hidden_agent = Participant.create_participants(hidden)
        Message.objects.create(
            session=hidden, sender=hidden_user, text="secret test line"
        )

        active_hidden = Session.objects.create(
            consumer=self.consumer_one,
            exercise=hidden_exercise,
            authoring_test=True,
            completed=False,
            abandoned=False,
            current_step_no=1,
            total_steps_no=1,
        )

        history = TestCase._get(
            "/sessions",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(history.status_code, status.HTTP_200_OK, history.json)
        history_ids = {row["id"] for row in history.json["results"]}
        self.assertIn(real.id, history_ids)
        self.assertNotIn(hidden.id, history_ids)
        self.assertNotIn(active_hidden.id, history_ids)

        resume = TestCase._get(
            "/sessions",
            query_params_dict={"general": "false"},
            access_token=self.consumer_one_access_token,
        )
        resume_ids = {row["id"] for row in resume.json["results"]}
        self.assertNotIn(active_hidden.id, resume_ids)

        self.assertEqual(
            list(completed_runs_queryset(self.consumer_one).values_list("id", flat=True)),
            [real.id],
        )
        runs = TestCase._get(
            "/runs",
            query_params_dict={"status": "completed"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(runs.status_code, status.HTTP_200_OK, runs.json)
        self.assertEqual([row["id"] for row in runs.json["results"]], [real.id])

        today = DateUtils.progress_calendar_date()
        progress = get_exercises_progress(
            self.consumer_one, today - timedelta(days=1), today
        )
        self.assertEqual(progress["total_completions"], 1)
        self.assertEqual(get_streaks(self.consumer_one)["exercise"]["current"], 1)
        excerpt = _recent_transcript_excerpt(self.consumer_one, days=7)
        self.assertIn("a real reply", excerpt)
        self.assertNotIn("secret test line", excerpt)
        self.assertFalse(has_completed_exercise_before(self.consumer_one, hidden_exercise))

        general = Session.objects.create(consumer=self.consumer_one, exercise=None)
        context = render_session_context(self.consumer_one, general)
        self.assertNotIn("Hidden test exercise", context)
        self.assertIn("Real run exercise", context)

    def test_idle_closer_leaves_flagged_sessions_open(self):
        flagged = Session.objects.create(
            consumer=self.consumer_one,
            authoring_test=True,
            completed=False,
        )
        real = Session.objects.create(
            consumer=self.consumer_one,
            authoring_test=False,
            completed=False,
        )
        old = timezone.now() - timedelta(hours=5)
        for session in (flagged, real):
            _user, agent = Participant.create_participants(session)
            message = Message.objects.create(session=session, sender=agent, text="hi")
            Message.objects.filter(id=message.id).update(created_at=old)
            session.last_message = message
            session.save(update_fields=["last_message", "updated_at"])

        with patch("api.utils.AI.AI.ask", side_effect=_ai_payload):
            closed = close_idle_sessions()

        flagged.refresh_from_db()
        real.refresh_from_db()
        self.assertGreaterEqual(closed, 1)
        self.assertIsNone(flagged.closed_at)
        self.assertIsNotNone(real.closed_at)

    def test_snapshot_exercises_are_hidden(self):
        visible = General.create_exercise()
        visible.title = "Visible catalogue exercise"
        visible.status = Constants.EXERCISE_STATUS_PUBLISHED
        visible.authoring_snapshot = False
        visible.save(update_fields=["title", "status", "authoring_snapshot", "updated_at"])

        hidden = General.create_exercise()
        hidden.title = "Hidden snapshot exercise"
        hidden.status = Constants.EXERCISE_STATUS_PUBLISHED
        hidden.authoring_snapshot = True
        hidden.save(update_fields=["title", "status", "authoring_snapshot", "updated_at"])

        for token in (self.consumer_one_access_token, self.admin_one_access_token):
            listed = TestCase._get(
                "/exercises",
                query_params_dict={"search_term": "Hidden snapshot exercise"},
                access_token=token,
            )
            self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
            self.assertEqual(listed.json["results"], [])

            detail = TestCase._get(
                f"/exercises/{hidden.id}",
                access_token=token,
            )
            self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

        found = TestCase._get(
            "/exercises",
            query_params_dict={"search_term": "Visible catalogue exercise"},
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(
            [row["id"] for row in found.json["results"]],
            [visible.id],
        )
        self.assertFalse(
            Exercise.objects.filter(id=hidden.id, authoring_snapshot=False).exists()
        )


_OPENING_TEXT = "Welcome. This is the test opening."


def _fake_opening(session, consumer_message):
    """Stand in for the greeting model. The greeting does not call AI.ask."""
    return (
        ExerciseStateResponse(
            text=_OPENING_TEXT,
            reasoning="test",
            suggested_responses=[],
            question_kind="none",
            step_goal_met=False,
            asks_readiness=False,
            risk_level="none",
        ),
        {},
        None,
        None,
    )


class AuthoringRunTestCase(BaseTest):
    def endpoint(self):
        return "exercises"

    def setUp(self):
        # BaseTest creates a consumer, which sends mail. The greeting calls
        # the agent, not AI.ask, so both are patched before any of that runs.
        self._resend = patch("resend.Emails.send", return_value={"id": "email_test"})
        self._ask = patch("api.utils.AI.AI.ask", side_effect=_ai_payload)
        self._model = patch("api.utils.Agent.get_response", side_effect=_fake_opening)
        self.resend = self._resend.start()
        self._ask.start()
        self.model = self._model.start()
        try:
            super().setUp()
        except Exception:
            self._stop_patches()
            raise

    def tearDown(self):
        self._stop_patches()
        super().tearDown()

    def _stop_patches(self):
        self._model.stop()
        self._ask.stop()
        self._resend.stop()

    def _draft(self):
        exercise = General.create_exercise()
        exercise.status = Constants.EXERCISE_STATUS_DRAFT
        exercise.completions_no = 4
        exercise.featured = True
        exercise.check_in_enabled = True
        exercise.save(
            update_fields=[
                "status",
                "completions_no",
                "featured",
                "check_in_enabled",
                "updated_at",
            ]
        )
        return exercise


class AuthoringSnapshotTests(AuthoringRunTestCase):
    """Snapshot writer and POST /exercises/<id>/test-runs."""

    def test_unsaved_step_instruction_is_what_the_snapshot_stores(self):
        exercise = self._draft()
        step = exercise.steps.order_by("order").first()
        saved_instructions = step.instructions
        saved_step_count = exercise.steps.count()
        marker = "UNSAVED-STEP-INSTRUCTION"
        tag = Tag.objects.create(name="Focus")
        tag_count = Tag.objects.count()
        question = Question.objects.create(
            exercise=exercise,
            type=Constants.QUESTION_TYPE_TEXT,
            title="Saved question",
            order=0,
        )
        paused = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=False,
            abandoned=False,
            current_step_no=2,
            total_steps_no=saved_step_count,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )

        snapshot = write_authoring_snapshot(
            exercise,
            {
                "check_in_enabled": True,
                "featured": True,
                "steps": [
                    {"id": step.id, "instructions": marker, "tags": [tag.id]},
                    {
                        "title": "Unsaved extra step",
                        "description": "Not in the saved exercise",
                        "instructions": "Do the new step",
                        "completion_label": "Done",
                    },
                ],
                "questions": [{"id": question.id, "title": "Unsaved question"}],
            },
        )

        exercise.refresh_from_db()
        step.refresh_from_db()
        question.refresh_from_db()
        paused.refresh_from_db()

        self.assertTrue(snapshot.authoring_snapshot)
        self.assertEqual(snapshot.authoring_source_id, exercise.id)
        self.assertNotEqual(snapshot.id, exercise.id)
        self.assertEqual(snapshot.status, Constants.EXERCISE_STATUS_DRAFT)
        self.assertEqual(snapshot.completions_no, 0)
        self.assertFalse(snapshot.featured)
        self.assertFalse(snapshot.check_in_enabled)
        self.assertEqual(exercise.completions_no, 4)
        self.assertTrue(exercise.featured)
        self.assertEqual(exercise.status, Constants.EXERCISE_STATUS_DRAFT)
        self.assertEqual(step.instructions, saved_instructions)
        self.assertEqual(exercise.steps.count(), saved_step_count)
        self.assertEqual(snapshot.steps.count(), 2)
        self.assertEqual(snapshot.sessions.count(), 0)
        self.assertFalse(paused.abandoned)

        copied = snapshot.steps.get(instructions=marker)
        self.assertEqual(copied.title, step.title)
        self.assertNotEqual(copied.id, step.id)
        self.assertEqual(list(copied.tags.values_list("id", flat=True)), [tag.id])
        self.assertEqual(Tag.objects.count(), tag_count)
        self.assertTrue(snapshot.steps.filter(title="Unsaved extra step").exists())

        copied_question = snapshot.questions.get()
        self.assertEqual(copied_question.title, "Unsaved question")
        self.assertNotEqual(copied_question.id, question.id)
        self.assertIsNone(copied_question.session_id)
        self.assertEqual(question.title, "Saved question")

        full = write_authoring_snapshot(exercise, {})
        self.assertEqual(
            list(full.steps.order_by("order").values_list("title", flat=True)),
            list(exercise.steps.order_by("order").values_list("title", flat=True)),
        )
        source_question_ids = set(exercise.questions.values_list("id", flat=True))
        copied_question_ids = set(full.questions.values_list("id", flat=True))
        self.assertTrue(copied_question_ids)
        self.assertTrue(copied_question_ids.isdisjoint(source_question_ids))
        self.assertFalse(full.questions.filter(session__isnull=False).exists())

    def test_admin_starts_a_flagged_run_at_step_one(self):
        exercise = self._draft()
        step = exercise.steps.order_by("order").first()
        marker = "UNSAVED-STEP-INSTRUCTION"
        question = Question.objects.create(
            exercise=exercise,
            type=Constants.QUESTION_TYPE_TEXT,
            title="Saved question",
            order=0,
        )
        paused = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=False,
            abandoned=False,
            current_step_no=2,
            total_steps_no=exercise.steps.count(),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        metrics_before = SessionMetric.objects.count()
        knowledge_before = KnowledgeEntry.objects.count()
        summaries_before = Summary.objects.count()
        exercise_summaries_before = ExerciseSummary.objects.count()
        mail_before = self.resend.call_count

        with patch("api.tasks.notify_trust_and_safety.delay_on_commit") as notify:
            response = self._post(
                f"/exercises/{exercise.id}/test-runs",
                {
                    "consumer_id": self.consumer_one.user_id,
                    "check_in_enabled": True,
                    "steps": [
                        {"id": step.id, "instructions": marker},
                        {
                            "title": "Unsaved extra step",
                            "description": "Not in the saved exercise",
                            "instructions": "Do the new step",
                            "completion_label": "Done",
                        },
                    ],
                    "questions": [{"id": question.id, "title": "Unsaved question"}],
                },
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["opening_message"], _OPENING_TEXT)
        self.assertEqual(response.json["session_state"]["phase"], Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(response.json["session_state"]["current_step_no"], 1)
        self.assertFalse(notify.called)
        self.assertEqual(self.resend.call_count, mail_before)

        started = Session.objects.get(id=response.json["session_id"])
        snapshot = Exercise.objects.get(id=response.json["snapshot_exercise_id"])
        self.assertTrue(started.authoring_test)
        self.assertEqual(started.exercise_id, snapshot.id)
        self.assertNotEqual(started.exercise_id, exercise.id)
        self.assertEqual(started.current_step_no, 1)
        self.assertEqual(started.state, Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertFalse(started.in_pre_exercise_phase())
        self.assertFalse(started.questions.exists())
        self.assertEqual(snapshot.steps.order_by("order").first().instructions, marker)
        self.assertTrue(snapshot.questions.filter(session__isnull=True).exists())
        self.assertFalse(snapshot.check_in_enabled)

        paused.refresh_from_db()
        exercise.refresh_from_db()
        self.assertFalse(paused.abandoned)
        self.assertEqual(paused.exercise_id, exercise.id)
        self.assertEqual(paused.current_step_no, 2)
        self.assertFalse(paused.authoring_test)
        self.assertEqual(exercise.completions_no, 4)
        self.assertEqual(SessionMetric.objects.count(), metrics_before)
        self.assertEqual(KnowledgeEntry.objects.count(), knowledge_before)
        self.assertEqual(Summary.objects.count(), summaries_before)
        self.assertEqual(ExerciseSummary.objects.count(), exercise_summaries_before)

    def test_consumer_and_admin_without_pii_are_rejected(self):
        exercise = self._draft()
        completions = exercise.completions_no
        metrics_before = SessionMetric.objects.count()
        knowledge_before = KnowledgeEntry.objects.count()
        summaries_before = Summary.objects.count()
        mail_before = self.resend.call_count
        body = {"consumer_id": self.consumer_one.user_id, "steps": []}

        consumer_response = self._post(
            f"/exercises/{exercise.id}/test-runs",
            body,
            self.consumer_one_access_token,
        )
        self.assertEqual(consumer_response.status_code, status.HTTP_403_FORBIDDEN)

        missing_exercise = self._post(
            "/exercises/exrcs_missing/test-runs",
            body,
            self.admin_one_access_token,
        )
        self.assertEqual(missing_exercise.status_code, status.HTTP_404_NOT_FOUND)

        unknown_consumer = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": "user_missing"},
            self.admin_one_access_token,
        )
        self.assertEqual(unknown_consumer.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(unknown_consumer.json["consumer_id"], "Consumer not found")

        missing_consumer = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {},
            self.admin_one_access_token,
        )
        self.assertEqual(missing_consumer.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            missing_consumer.json["consumer_id"],
            "Choose a user to dry-run against.",
        )

        self.admin_one.role.permissions.pii = []
        self.admin_one.role.permissions.save()
        hidden = self._post(
            f"/exercises/{exercise.id}/test-runs",
            body,
            self.admin_one_access_token,
        )
        self.assertEqual(hidden.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            hidden.json["detail"],
            "Personal Information view permission is required to test against a user",
        )

        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, completions)
        self.assertFalse(Session.objects.filter(authoring_test=True).exists())
        self.assertFalse(Exercise.objects.filter(authoring_snapshot=True).exists())
        self.assertEqual(SessionMetric.objects.count(), metrics_before)
        self.assertEqual(KnowledgeEntry.objects.count(), knowledge_before)
        self.assertEqual(Summary.objects.count(), summaries_before)
        self.assertEqual(self.resend.call_count, mail_before)

    def test_model_failure_returns_502_and_keeps_nothing(self):
        exercise = self._draft()
        # The real greeting catches a provider error and returns a stock
        # sentence. Stop the stand-in so this test hits that path.
        self._model.stop()
        try:
            with patch(
                "api.utils.Agent.run_with_failover",
                side_effect=RuntimeError("model down"),
            ):
                response = self._post(
                    f"/exercises/{exercise.id}/test-runs",
                    {"consumer_id": self.consumer_one.user_id},
                    self.admin_one_access_token,
                )
        finally:
            self._model.start()

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY, response.json)
        self.assertIn("model down", response.json["detail"])
        self.assertFalse(Exercise.all_objects.filter(authoring_snapshot=True).exists())
        self.assertFalse(Session.all_objects.filter(authoring_test=True).exists())
        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)

    def test_prompt_uses_the_source_summary_and_last_run(self):
        exercise = self._draft()
        step = exercise.steps.order_by("order").first()
        step.instructions = "Ask about {{last_run.check_in_summary}}"
        step.save(update_fields=["instructions", "updated_at"])
        ExerciseSummary.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            detailed="SOURCE SUMMARY MARKER",
        )
        Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=True,
            completed_at=timezone.now(),
            pre_exercise_prompt_summary="LAST RUN MARKER",
            current_step_no=2,
            state=Constants.SESSION_STATE_COMPLETED,
        )
        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=False,
            current_step_no=1,
            total_steps_no=exercise.steps.count(),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        snapshot = write_authoring_snapshot(exercise, {})
        flagged = Session.objects.create(
            consumer=self.consumer_one,
            exercise=snapshot,
            authoring_test=True,
            completed=False,
            current_step_no=1,
            total_steps_no=snapshot.steps.count(),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        summaries_before = ExerciseSummary.objects.count()

        test_prompt = _prepare_prompt(flagged)
        real_prompt = _prepare_prompt(real)

        self.assertIn("SOURCE SUMMARY MARKER", test_prompt)
        self.assertIn("LAST RUN MARKER", test_prompt)
        self.assertIn("SOURCE SUMMARY MARKER", real_prompt)
        self.assertIn("LAST RUN MARKER", real_prompt)
        self.assertFalse(ExerciseSummary.objects.filter(exercise=snapshot).exists())
        self.assertEqual(ExerciseSummary.objects.count(), summaries_before)

    def test_opening_line_matches_a_real_start(self):
        exercise = self._draft()
        response = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": self.consumer_one.user_id},
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        hidden = self.model.call_args.kwargs["consumer_message"].text
        self.assertEqual(hidden, opening_turn(1))
        self.assertNotIn("greet me and explain", hidden)


def _agent_turn(text, goal=False, asks=False, reasoning="test"):
    return ExerciseStateResponse(
        text=text,
        reasoning=reasoning,
        suggested_responses=[],
        question_kind="none",
        step_goal_met=goal,
        asks_readiness=asks,
        risk_level="none",
    )


def _script(turns):
    pending = list(turns)

    def _fake(session, consumer_message):
        if not pending:
            raise AssertionError("The model was called more times than the script allows.")
        return (pending.pop(0), {}, None, None)

    return _fake


class AuthoringMessageTests(AuthoringRunTestCase):
    """POST /exercises/<id>/test-runs/<run_id>/messages."""

    def _start(self, exercise, steps=None):
        body = {"consumer_id": self.consumer_one.user_id}
        if steps is not None:
            body["steps"] = steps
        response = self._post(
            f"/exercises/{exercise.id}/test-runs",
            body,
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        return response

    def _message(self, exercise, session_id, text, from_suggested_response=False, token=None):
        body = {"text": text}
        if from_suggested_response:
            body["from_suggested_response"] = True
        return self._post(
            f"/exercises/{exercise.id}/test-runs/{session_id}/messages",
            body,
            token or self.admin_one_access_token,
        )

    def _awaiting(self, session_id, finish=False):
        session = Session.objects.get(id=session_id)
        session.state = Constants.SESSION_STATE_AWAITING_READY
        session.save(update_fields=["state", "updated_at"])
        message = session.last_message
        if finish:
            message.suggested_responses = [Constants.CHIP_FINISH, Constants.CHIP_NOT_YET]
            message.suggested_responses_kind = Constants.SUGGESTED_RESPONSES_KIND_FINISH
        else:
            message.suggested_responses = [Constants.CHIP_READY_YES, Constants.CHIP_NOT_YET]
            message.suggested_responses_kind = Constants.SUGGESTED_RESPONSES_KIND_READY
        message.question_kind = Constants.QUESTION_KIND_READINESS
        message.save(
            update_fields=[
                "suggested_responses",
                "suggested_responses_kind",
                "question_kind",
                "updated_at",
            ]
        )
        return session

    def test_typed_reply_stays_on_the_step(self):
        exercise = self._draft()
        started = self._start(exercise)
        session_id = started.json["session_id"]

        with patch(
            "api.utils.Agent.get_response",
            side_effect=_script([_agent_turn("Tell me the thought.")]),
        ):
            response = self._message(exercise, session_id, "I keep thinking I will fail.")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["text"], "Tell me the thought.")
        self.assertEqual(response.json["suggested_responses"], [])
        self.assertEqual(response.json["question_kind"], Constants.QUESTION_KIND_NONE)
        self.assertEqual(response.json["user_message"]["text"], "I keep thinking I will fail.")
        self.assertEqual(response.json["session_state"]["phase"], Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(response.json["session_state"]["current_step_no"], 1)
        self.assertNotIn("completion_card", response.json["session_state"])

        saved = Message.objects.get(id=response.json["user_message"]["id"])
        self.assertEqual(saved.sender.consumer_id, self.consumer_one.user_id)
        session = Session.objects.get(id=session_id)
        self.assertFalse(session.completed)

    def test_ready_chip_advances_a_step(self):
        exercise = self._draft()
        started = self._start(exercise)
        session_id = started.json["session_id"]
        self._awaiting(session_id)
        before = self.model.call_count

        with patch(
            "api.utils.Agent.get_response",
            side_effect=_script([_agent_turn("On to step 2.")]),
        ) as chat:
            response = self._message(
                exercise,
                session_id,
                Constants.CHIP_READY_YES,
                from_suggested_response=True,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(self.model.call_count, before)
        self.assertEqual(response.json["text"], "On to step 2.")
        self.assertEqual(response.json["user_message"]["text"], Constants.CHIP_READY_YES)
        self.assertEqual(response.json["session_state"]["phase"], Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertEqual(response.json["session_state"]["current_step_no"], 2)
        self.assertIn("completion_card", response.json["session_state"])
        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)

    def test_finish_chip_completes_the_run(self):
        exercise = self._draft()
        step = exercise.steps.order_by("order").first()
        started = self._start(exercise, steps=[{"id": step.id, "order": 0}])
        session_id = started.json["session_id"]
        self._awaiting(session_id, finish=True)
        before = self.model.call_count

        response = self._message(
            exercise,
            session_id,
            Constants.CHIP_FINISH,
            from_suggested_response=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(self.model.call_count, before)
        self.assertEqual(response.json["user_message"]["text"], Constants.CHIP_FINISH)
        self.assertEqual(response.json["session_state"]["phase"], Constants.SESSION_STATE_COMPLETED)
        self.assertEqual(response.json["session_state"]["current_step_no"], 2)
        self.assertIn("completion_card", response.json["session_state"])

        session = Session.objects.get(id=session_id)
        self.assertTrue(session.completed)
        self.assertIsNotNone(session.completed_at)
        self.assertIsNone(session.closed_at)
        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)
        snapshot = Exercise.objects.get(id=started.json["snapshot_exercise_id"])
        self.assertEqual(snapshot.completions_no, 0)

    def test_two_step_run_leaves_real_data_unchanged(self):
        exercise = self._draft()
        steps = list(exercise.steps.order_by("order")[:2])
        metrics_before = SessionMetric.objects.count()
        knowledge_before = KnowledgeEntry.objects.count()
        summaries_before = Summary.objects.count()
        exercise_summaries_before = ExerciseSummary.objects.count()
        mail_before = self.resend.call_count
        paused = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=False,
            abandoned=False,
            current_step_no=2,
            total_steps_no=exercise.steps.count(),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )

        self._model.stop()
        try:
            with (
                patch(
                    "api.utils.Agent.get_response",
                    side_effect=_script([
                        _agent_turn("Welcome to step 1."),
                        _agent_turn("Ready to move on?", goal=True, asks=True),
                        _agent_turn("Here is step 2."),
                        _agent_turn("Ready to finish?", goal=True, asks=True),
                    ]),
                ),
                patch("api.tasks.notify_trust_and_safety.delay_on_commit") as notify,
            ):
                started = self._start(
                    exercise,
                    steps=[
                        {"id": steps[0].id, "order": 0},
                        {"id": steps[1].id, "order": 1},
                    ],
                )
                session_id = started.json["session_id"]
                first = self._message(exercise, session_id, "The thought is that I will fail.")
                ready = self._message(
                    exercise,
                    session_id,
                    Constants.CHIP_READY_YES,
                    from_suggested_response=True,
                )
                second = self._message(exercise, session_id, "A fairer thought is that I can prepare.")
                finished = self._message(
                    exercise,
                    session_id,
                    Constants.CHIP_FINISH,
                    from_suggested_response=True,
                )
        finally:
            self._model.start()

        self.assertEqual(first.status_code, status.HTTP_200_OK, first.json)
        self.assertEqual(first.json["session_state"]["phase"], Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(first.json["session_state"]["current_step_no"], 1)
        self.assertEqual(first.json["session_state"]["pending_action"], "ready")

        self.assertEqual(ready.status_code, status.HTTP_200_OK, ready.json)
        self.assertEqual(ready.json["text"], "Here is step 2.")
        self.assertEqual(ready.json["session_state"]["current_step_no"], 2)
        self.assertEqual(ready.json["session_state"]["phase"], Constants.SESSION_STATE_STEP_ACTIVE)
        self.assertIn("completion_card", ready.json["session_state"])

        self.assertEqual(second.status_code, status.HTTP_200_OK, second.json)
        self.assertEqual(second.json["session_state"]["phase"], Constants.SESSION_STATE_AWAITING_READY)
        self.assertEqual(second.json["session_state"]["pending_action"], "finish")

        self.assertEqual(finished.status_code, status.HTTP_200_OK, finished.json)
        self.assertEqual(finished.json["session_state"]["phase"], Constants.SESSION_STATE_COMPLETED)
        self.assertEqual(finished.json["session_state"]["current_step_no"], 3)
        self.assertIn("completion_card", finished.json["session_state"])
        self.assertEqual(
            [step["status"] for step in finished.json["session_state"]["steps"]],
            ["completed", "completed"],
        )
        self.assertFalse(notify.called)

        session = Session.objects.get(id=session_id)
        self.assertTrue(session.completed)
        self.assertIsNone(session.closed_at)
        exercise.refresh_from_db()
        paused.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)
        self.assertFalse(paused.abandoned)
        self.assertEqual(paused.current_step_no, 2)
        self.assertEqual(SessionMetric.objects.count(), metrics_before)
        self.assertEqual(KnowledgeEntry.objects.count(), knowledge_before)
        self.assertEqual(Summary.objects.count(), summaries_before)
        self.assertEqual(ExerciseSummary.objects.count(), exercise_summaries_before)
        self.assertEqual(self.resend.call_count, mail_before)
        self.assertEqual(
            Exercise.objects.get(id=started.json["snapshot_exercise_id"]).completions_no,
            0,
        )

    def test_wrong_session_and_a_finished_run_are_rejected(self):
        exercise = self._draft()
        other = self._draft()
        started = self._start(exercise)
        session_id = started.json["session_id"]
        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            completed=False,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )

        consumer = self._message(
            exercise,
            session_id,
            "Hello",
            token=self.consumer_one_access_token,
        )
        self.assertEqual(consumer.status_code, status.HTTP_403_FORBIDDEN)

        missing = self._message(exercise, real.id, "Hello")
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)

        other_exercise = self._message(other, session_id, "Hello")
        self.assertEqual(other_exercise.status_code, status.HTTP_404_NOT_FOUND)

        empty = self._message(exercise, session_id, "  ")
        self.assertEqual(empty.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(empty.json["detail"], "Enter a message.")

        session = Session.objects.get(id=session_id)
        session.completed = True
        session.save(update_fields=["completed", "updated_at"])
        again = self._message(exercise, session_id, "Hello again")
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            again.json["session"],
            "Not allowed to send messages for past sessions.",
        )

    def test_message_model_failure_rolls_the_turn_back(self):
        exercise = self._draft()
        started = self._start(exercise)
        session_id = started.json["session_id"]
        before = Message.objects.filter(session_id=session_id).count()
        sorry = _agent_turn(
            "Sorry, I had an issue understanding your message, "
            "can you repeat it or rephrase it for me please?",
            reasoning="model down",
        )

        self._model.stop()
        try:
            with patch(
                "api.utils.Agent.get_response",
                return_value=(sorry, {}, None, None),
            ):
                response = self._message(exercise, session_id, "Hello")
        finally:
            self._model.start()

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY, response.json)
        self.assertIn("model down", response.json["detail"])
        self.assertEqual(Message.objects.filter(session_id=session_id).count(), before)
        session = Session.objects.get(id=session_id)
        self.assertEqual(session.current_step_no, 1)
        self.assertFalse(session.completed)


class AuthoringCleanupTests(AuthoringRunTestCase):
    """Delete, replace, and the idle sweeper only touch flagged runs."""

    def _start(self, exercise, token=None):
        response = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": self.consumer_one.user_id},
            token or self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        return response

    def _flagged(self, exercise, when=None, with_message=True):
        snapshot = write_authoring_snapshot(exercise, {})
        session = Session.objects.create(
            consumer=self.consumer_one,
            exercise=snapshot,
            authoring_test=True,
            authoring_admin=self.admin_one,
            current_step_no=1,
            total_steps_no=snapshot.steps.count(),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        if with_message:
            _user, agent = Participant.create_participants(session)
            message = Message.objects.create(session=session, sender=agent, text="hi")
            if when is not None:
                Message.objects.filter(id=message.id).update(created_at=when)
            session.last_message = message
            session.save(update_fields=["last_message", "updated_at"])
        elif when is not None:
            Session.objects.filter(id=session.id).update(updated_at=when)
        return session, snapshot

    def test_delete_removes_the_run_and_leaves_real_data(self):
        exercise = self._draft()
        started = self._start(exercise)
        session_id = started.json["session_id"]
        snapshot_id = started.json["snapshot_exercise_id"]
        self.assertTrue(Message.objects.filter(session_id=session_id).exists())
        self.assertTrue(SessionStep.objects.filter(session_id=session_id).exists())
        self.assertTrue(Participant.objects.filter(session_id=session_id).exists())
        self.assertTrue(Step.objects.filter(exercise_id=snapshot_id).exists())

        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        field = KnowledgeField.objects.create(
            key=f"kept_{exercise.id}",
            label="Kept",
            category="Worry",
            active=True,
        )
        entry = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=field,
            value="kept",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_EXERCISE,
            session_id=session_id,
        )
        metric = SessionMetric.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            session=real,
            key="mood",
            value=1,
            source=Constants.SESSION_METRIC_SOURCE_FORM,
            recorded_at=timezone.now(),
        )
        summaries_before = Summary.objects.count()
        exercise_summaries_before = ExerciseSummary.objects.count()

        response = TestCase._delete(
            f"/exercises/{exercise.id}/test-runs/{session_id}",
            self.admin_one_access_token,
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Session.all_objects.filter(id=session_id).exists())
        self.assertFalse(Message.all_objects.filter(session_id=session_id).exists())
        self.assertFalse(SessionStep.all_objects.filter(session_id=session_id).exists())
        self.assertFalse(Participant.all_objects.filter(session_id=session_id).exists())
        self.assertFalse(Question.all_objects.filter(exercise_id=snapshot_id).exists())
        self.assertFalse(Step.all_objects.filter(exercise_id=snapshot_id).exists())
        self.assertFalse(Exercise.all_objects.filter(id=snapshot_id).exists())

        self.assertTrue(Session.objects.filter(id=real.id).exists())
        self.assertTrue(Exercise.objects.filter(id=exercise.id).exists())
        exercise.refresh_from_db()
        self.assertEqual(exercise.completions_no, 4)
        entry.refresh_from_db()
        self.assertEqual(entry.value, "kept")
        self.assertIsNone(entry.session_id)
        self.assertTrue(SessionMetric.objects.filter(id=metric.id).exists())
        self.assertEqual(Summary.objects.count(), summaries_before)
        self.assertEqual(ExerciseSummary.objects.count(), exercise_summaries_before)

    def test_starting_a_run_replaces_that_admins_previous_run(self):
        exercise = self._draft()
        first = self._start(exercise)
        first_id = first.json["session_id"]

        self._model.stop()
        try:
            with patch("api.utils.Agent.get_response", side_effect=RuntimeError("model down")):
                failed = self._post(
                    f"/exercises/{exercise.id}/test-runs",
                    {"consumer_id": self.consumer_one.user_id},
                    self.admin_one_access_token,
                )
        finally:
            self._model.start()
        self.assertEqual(failed.status_code, status.HTTP_502_BAD_GATEWAY, failed.json)
        self.assertTrue(Session.objects.filter(id=first_id).exists())

        other = create_admin(email="authoring-other@example.com")
        other_token = get_access_token(other.user)
        theirs = self._start(exercise, token=other_token)
        second = self._start(exercise)

        self.assertFalse(Session.all_objects.filter(id=first_id).exists())
        self.assertFalse(
            Exercise.all_objects.filter(id=first.json["snapshot_exercise_id"]).exists()
        )
        self.assertTrue(Session.objects.filter(id=theirs.json["session_id"]).exists())
        self.assertTrue(Session.objects.filter(id=second.json["session_id"]).exists())
        self.assertEqual(
            list(
                Session.objects.filter(
                    authoring_test=True,
                    authoring_admin=self.admin_one,
                ).values_list("id", flat=True)
            ),
            [second.json["session_id"]],
        )

    def test_sweeper_deletes_an_old_run_and_leaves_a_recent_one(self):
        exercise = self._draft()
        old_at = timezone.now() - timedelta(hours=3)
        old_session, old_snapshot = self._flagged(exercise, when=old_at)
        recent_session, recent_snapshot = self._flagged(exercise)
        quiet_session, quiet_snapshot = self._flagged(exercise, when=old_at, with_message=False)
        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        _user, agent = Participant.create_participants(real)
        real_message = Message.objects.create(session=real, sender=agent, text="real")
        Message.objects.filter(id=real_message.id).update(created_at=old_at)
        real.last_message = real_message
        real.save(update_fields=["last_message", "updated_at"])

        setting = Setting.get_or_create_authoring_test_idle_minutes()
        setting.value = "10000"
        setting.save()
        with patch("api.utils.session_close.close_session") as close:
            self.assertEqual(sweep_authoring_test_runs(), 0)
        self.assertFalse(close.called)
        self.assertTrue(Session.objects.filter(id=old_session.id).exists())
        self.assertTrue(Session.objects.filter(id=recent_session.id).exists())

        setting.value = str(Constants.AUTHORING_TEST_IDLE_MINUTES)
        setting.save()
        with patch("api.utils.session_close.close_session") as close:
            deleted = sweep_authoring_test_runs()
        self.assertFalse(close.called)
        self.assertGreaterEqual(deleted, 2)
        self.assertFalse(Session.all_objects.filter(id=old_session.id).exists())
        self.assertFalse(Exercise.all_objects.filter(id=old_snapshot.id).exists())
        self.assertFalse(Session.all_objects.filter(id=quiet_session.id).exists())
        self.assertFalse(Exercise.all_objects.filter(id=quiet_snapshot.id).exists())
        self.assertTrue(Session.objects.filter(id=recent_session.id).exists())
        self.assertTrue(Exercise.objects.filter(id=recent_snapshot.id).exists())
        real.refresh_from_db()
        self.assertIsNone(real.closed_at)
        self.assertTrue(Exercise.objects.filter(id=exercise.id).exists())

    def test_sweeper_deletes_an_orphan_snapshot_and_leaves_a_real_exercise(self):
        exercise = self._draft()
        real_question_ids = set(exercise.questions.values_list("id", flat=True))
        self.assertTrue(real_question_ids)
        orphan = write_authoring_snapshot(exercise, {})
        self.assertTrue(orphan.authoring_snapshot)
        self.assertFalse(Session.objects.filter(exercise=orphan).exists())
        orphan_question_ids = list(orphan.questions.values_list("id", flat=True))
        self.assertTrue(orphan_question_ids)
        Exercise.objects.filter(pk=orphan.pk).update(
            updated_at=timezone.now() - timedelta(hours=3)
        )

        setting = Setting.get_or_create_authoring_test_idle_minutes()
        setting.value = str(Constants.AUTHORING_TEST_IDLE_MINUTES)
        setting.save()
        sweep_authoring_test_runs()

        self.assertFalse(Exercise.all_objects.filter(id=orphan.id).exists())
        self.assertFalse(Question.all_objects.filter(id__in=orphan_question_ids).exists())
        self.assertTrue(Exercise.objects.filter(id=exercise.id).exists())
        self.assertEqual(
            set(Question.objects.filter(exercise=exercise).values_list("id", flat=True)),
            real_question_ids,
        )

    def test_non_test_session_is_refused(self):
        exercise = self._draft()
        real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=False,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        with self.assertRaises(AuthoringDeleteRefused):
            delete_authoring_run(real)
        self.assertTrue(Session.objects.filter(id=real.id).exists())
        self.assertTrue(Exercise.objects.filter(id=exercise.id).exists())

        response = TestCase._delete(
            f"/exercises/{exercise.id}/test-runs/{real.id}",
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        flagged_on_real = Session.objects.create(
            consumer=self.consumer_one,
            exercise=exercise,
            authoring_test=True,
            current_step_no=1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        with self.assertRaises(AuthoringDeleteRefused):
            delete_authoring_run(flagged_on_real)
        self.assertTrue(Session.objects.filter(id=flagged_on_real.id).exists())
        self.assertTrue(Exercise.objects.filter(id=exercise.id).exists())


