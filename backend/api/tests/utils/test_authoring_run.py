"""A finished exercise-builder test run stays on its own session."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status

from ...exercise.models import Exercise
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
