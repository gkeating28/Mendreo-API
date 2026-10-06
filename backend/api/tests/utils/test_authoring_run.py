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
from ...session.models import Session, SessionMetric
from ...summary.models import Summary
from ...utils import Constants, DateUtils
from ...utils.Agent import ExerciseStateResponse
from ...utils.authoring_run import write_authoring_snapshot
from ...utils.form_answers import record_onboarding_knowledge, save_form_answer
from ...utils.prompt_blocks import render_session_context
from ...utils.risk import apply_turn_risk
from ...utils.SessionStateMachine import _confirm
from ...utils.session_close import close_idle_sessions
from ..TestCase import TestCase
from ..utils.BaseTest import BaseTest
from ..utils.manager import General


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


class AuthoringSnapshotTests(BaseTest):
    """Snapshot writer and POST /exercises/<id>/test-runs."""

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
        self._model.start()
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

