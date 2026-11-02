from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from ...setting.models import Setting
from ...utils import Constants
from ...utils.session_close import _update_run_summary, close_session, shape_run_summary
from ...utils.summary_prompts import (
    DEFAULT_RUN_SUMMARY_PROMPT,
    DEFAULT_RUN_SUMMARY_TONE_GUIDE,
)


class _FakeSession:
    def __init__(self, **kwargs):
        self.id = "ssn_test"
        self.closed_at = None
        self.close_reason = None
        self.completed = True
        self.exercise_id = "ex_1"
        self.authoring_test = False
        self.live_risk_level = "none"
        self.risk_level = "low"
        self.run_summary = None
        user = type("User", (), {"first_name": "Sam"})()
        self.consumer = type("Consumer", (), {"user": user})()
        for key, value in kwargs.items():
            setattr(self, key, value)

    def save(self, update_fields=None):
        self.saved_fields = update_fields


class RunSummaryShapeTests(SimpleTestCase):
    def test_bullets_are_capped_and_trimmed(self):
        shaped = shape_run_summary(
            {
                "line": "one two three",
                "bullets": ["alpha beta", "c", "d", "e", "f", "g", ""],
            },
            6,
        )
        self.assertEqual(shaped["line"], "one two three")
        self.assertEqual(shaped["bullets"], ["alpha beta", "c"])
        words = " ".join([shaped["line"], *shaped["bullets"]]).split()
        self.assertLessEqual(len(words), 6)
        self.assertEqual(len(shaped["bullets"]), 2)


class RunSummaryGeneratorTests(SimpleTestCase):
    def test_high_risk_skips_the_model(self):
        cases = (
            {"live_risk_level": "high"},
            {"risk_level": "high"},
            {"risk_level": "critical"},
        )
        for kwargs in cases:
            session = _FakeSession(**kwargs)
            with patch("api.utils.AI.AI.ask") as ask:
                _update_run_summary(session)
            ask.assert_not_called()
            self.assertIsNone(session.run_summary)

    def test_authoring_test_skips_the_generator(self):
        session = _FakeSession(authoring_test=True)
        with patch("api.utils.session_close._update_run_summary") as generate:
            close_session(session, "completed")
        generate.assert_not_called()
        self.assertIsNotNone(session.closed_at)
        self.assertIsNone(session.run_summary)

        direct = _FakeSession(authoring_test=True, closed_at=None)
        with patch("api.utils.AI.AI.ask") as ask:
            _update_run_summary(direct)
        ask.assert_not_called()
        self.assertIsNone(direct.run_summary)

    def test_model_failure_leaves_the_session_closed_with_no_summary(self):
        session = _FakeSession()
        with (
            patch("api.utils.session_close._rate"),
            patch("api.utils.session_close._extract_pending_question"),
            patch("api.utils.session_close._update_exercise_summary"),
            patch(
                "api.utils.session_close._run_summary_inputs",
                return_value=("check-in", "Step: result", "Client: hello"),
            ),
            patch.object(Setting, "get_run_summary_prompt", return_value="Write it"),
            patch.object(Setting, "get_run_summary_tone_guide", return_value=""),
            patch.object(Setting, "get_run_summary_max_length", return_value=40),
            patch("api.utils.AI.AI.ask", side_effect=RuntimeError("down")),
        ):
            close_session(session, "completed")
        self.assertIsNotNone(session.closed_at)
        self.assertIsNone(session.run_summary)

    def test_first_close_still_rates_extracts_and_summarises(self):
        session = _FakeSession(completed=True)
        with (
            patch("api.utils.session_close._rate") as rate,
            patch("api.utils.session_close._extract_pending_question") as extract,
            patch("api.utils.session_close._update_exercise_summary") as exercise_summary,
            patch("api.utils.session_close._update_run_summary") as run_summary,
        ):
            close_session(session, "completed")
        rate.assert_called_once_with(session)
        extract.assert_called_once_with(session)
        exercise_summary.assert_called_once_with(session)
        run_summary.assert_called_once_with(session)
        self.assertEqual(session.close_reason, "completed")
        self.assertIsNotNone(session.closed_at)

    def test_first_client_close_of_an_open_run_does_not_write_a_summary(self):
        session = _FakeSession(completed=False)
        with (
            patch("api.utils.session_close._rate") as rate,
            patch("api.utils.session_close._extract_pending_question") as extract,
            patch("api.utils.session_close._update_exercise_summary") as exercise_summary,
            patch("api.utils.session_close._update_run_summary") as run_summary,
        ):
            close_session(session, "client")
        rate.assert_called_once_with(session)
        extract.assert_called_once_with(session)
        exercise_summary.assert_not_called()
        run_summary.assert_not_called()
        self.assertEqual(session.close_reason, "client")
        self.assertIsNotNone(session.closed_at)

    def test_completing_a_client_closed_session_writes_the_run_summary_once(self):
        stamp = "2026-11-02T10:49:52+00:00"
        session = _FakeSession(closed_at=stamp, close_reason="client", completed=True)
        summary = {"line": "You stayed with it", "bullets": ["The worry shrank"]}
        with self._summary_patches(summary) as (ask, rate, extract, exercise_summary):
            with self.assertLogs("api.utils.session_close", level="INFO") as logs:
                close_session(session, "completed")
        ask.assert_called_once()
        rate.assert_not_called()
        extract.assert_not_called()
        exercise_summary.assert_not_called()
        self.assertEqual(session.run_summary, summary)
        self.assertEqual(session.closed_at, stamp)
        self.assertEqual(session.close_reason, "client")
        self.assertIn(
            "Run summary written after early close for ssn_test",
            "\n".join(logs.output),
        )

        with self._summary_patches(summary) as (ask, rate, extract, exercise_summary):
            close_session(session, "completed")
        ask.assert_not_called()
        rate.assert_not_called()
        extract.assert_not_called()
        exercise_summary.assert_not_called()
        self.assertEqual(session.run_summary, summary)
        self.assertEqual(session.closed_at, stamp)
        self.assertEqual(session.close_reason, "client")

    def test_high_risk_already_closed_session_is_skipped(self):
        for kwargs in (
            {"live_risk_level": "high"},
            {"risk_level": "high"},
            {"risk_level": "critical"},
        ):
            session = _FakeSession(
                closed_at="stamp",
                close_reason="client",
                completed=True,
                **kwargs,
            )
            with patch("api.utils.AI.AI.ask") as ask:
                close_session(session, "completed")
            ask.assert_not_called()
            self.assertIsNone(session.run_summary)
            self.assertEqual(session.closed_at, "stamp")
            self.assertEqual(session.close_reason, "client")

    def test_authoring_test_already_closed_is_untouched(self):
        session = _FakeSession(
            authoring_test=True,
            closed_at="stamp",
            close_reason="client",
            completed=True,
        )
        with (
            patch("api.utils.AI.AI.ask") as ask,
            patch("api.utils.session_close._update_run_summary") as generate,
            patch("api.utils.session_close._rate") as rate,
            patch("api.utils.session_close._extract_pending_question") as extract,
            patch("api.utils.session_close._update_exercise_summary") as exercise_summary,
        ):
            close_session(session, "completed")
        ask.assert_not_called()
        generate.assert_not_called()
        rate.assert_not_called()
        extract.assert_not_called()
        exercise_summary.assert_not_called()
        self.assertEqual(session.closed_at, "stamp")
        self.assertEqual(session.close_reason, "client")
        self.assertIsNone(session.run_summary)

    def _summary_patches(self, summary):
        return _SummaryPatches(summary)


class _SummaryPatches:
    def __init__(self, summary):
        self.summary = summary
        self._stack = None

    def __enter__(self):
        from contextlib import ExitStack

        stack = ExitStack()
        self._stack = stack
        ask = stack.enter_context(
            patch("api.utils.AI.AI.ask", return_value=self.summary)
        )
        rate = stack.enter_context(patch("api.utils.session_close._rate"))
        extract = stack.enter_context(
            patch("api.utils.session_close._extract_pending_question")
        )
        exercise_summary = stack.enter_context(
            patch("api.utils.session_close._update_exercise_summary")
        )
        stack.enter_context(
            patch(
                "api.utils.session_close._run_summary_inputs",
                return_value=("check-in", "Step: result", "Client: hello"),
            )
        )
        stack.enter_context(
            patch.object(Setting, "get_run_summary_prompt", return_value="Write it")
        )
        stack.enter_context(
            patch.object(Setting, "get_run_summary_tone_guide", return_value="")
        )
        stack.enter_context(
            patch.object(Setting, "get_run_summary_max_length", return_value=40)
        )
        return ask, rate, extract, exercise_summary

    def __exit__(self, exc_type, exc, tb):
        return self._stack.__exit__(exc_type, exc, tb)


class _BackfillQuery:
    def __init__(self, rows):
        self.rows = list(rows)
        self.ordered = None
        self.sliced = None
        self.narrowed = None

    def order_by(self, *fields):
        self.ordered = fields
        return self

    def filter(self, **kwargs):
        self.narrowed = kwargs
        if "id" in kwargs:
            self.rows = [row for row in self.rows if row.id == kwargs["id"]]
        return self

    def __getitem__(self, item):
        self.sliced = item
        return self.rows[item]


class BackfillRunSummariesCommandTests(SimpleTestCase):
    def test_dry_run_makes_no_model_call_and_respects_limit(self):
        rows = [SimpleNamespace(id=f"ssn_{index}") for index in range(4)]
        query = _BackfillQuery(rows)
        out = StringIO()
        with (
            patch("api.session.models.Session.objects") as manager,
            patch("api.utils.AI.AI.ask") as ask,
            patch("api.utils.session_close._update_run_summary") as generate,
            patch("api.management.commands.backfill_run_summaries.time.sleep") as sleep,
        ):
            manager.filter.return_value = query
            call_command(
                "backfill_run_summaries",
                "--dry-run",
                "--limit",
                "2",
                stdout=out,
            )
        ask.assert_not_called()
        generate.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(
            manager.filter.call_args.kwargs,
            {
                "completed": True,
                "run_summary__isnull": True,
                "exercise__isnull": False,
                "authoring_test": False,
            },
        )
        self.assertEqual(query.ordered, ("-completed_at", "-updated_at", "-id"))
        self.assertEqual(query.sliced, slice(None, 2))
        self.assertEqual(
            out.getvalue().splitlines(),
            ["ssn_0", "ssn_1", "count 2"],
        )

    def test_dry_run_default_limit_is_50(self):
        rows = [SimpleNamespace(id=f"ssn_{index}") for index in range(60)]
        query = _BackfillQuery(rows)
        out = StringIO()
        with (
            patch("api.session.models.Session.objects") as manager,
            patch("api.utils.AI.AI.ask") as ask,
        ):
            manager.filter.return_value = query
            call_command("backfill_run_summaries", "--dry-run", stdout=out)
        ask.assert_not_called()
        self.assertEqual(query.sliced, slice(None, 50))
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[-1], "count 50")
        self.assertEqual(len(lines), 51)

    def test_session_id_limits_the_selection_to_one_row(self):
        rows = [SimpleNamespace(id=f"ssn_{index}") for index in range(3)]
        query = _BackfillQuery(rows)
        out = StringIO()
        with (
            patch("api.session.models.Session.objects") as manager,
            patch("api.utils.AI.AI.ask") as ask,
        ):
            manager.filter.return_value = query
            call_command(
                "backfill_run_summaries",
                "--dry-run",
                "--session-id",
                "ssn_1",
                stdout=out,
            )
        ask.assert_not_called()
        self.assertEqual(query.narrowed, {"id": "ssn_1"})
        self.assertEqual(out.getvalue().splitlines(), ["ssn_1", "count 1"])


class RunSummaryGetterTests(SimpleTestCase):
    def test_prompt_falls_back_when_missing_or_blank(self):
        with patch.object(Setting, "_cached_value", return_value=None):
            self.assertEqual(Setting.get_run_summary_prompt(), DEFAULT_RUN_SUMMARY_PROMPT)
        with patch.object(Setting, "_cached_value", return_value="  "):
            self.assertEqual(Setting.get_run_summary_prompt(), DEFAULT_RUN_SUMMARY_PROMPT)

    def test_tone_falls_back_to_blank(self):
        with patch.object(Setting, "_cached_value", return_value=None):
            self.assertEqual(
                Setting.get_run_summary_tone_guide(),
                DEFAULT_RUN_SUMMARY_TONE_GUIDE,
            )
        with patch.object(Setting, "_cached_value", return_value="  "):
            self.assertEqual(Setting.get_run_summary_tone_guide(), "")

    def test_max_length_falls_back_when_missing_or_blank(self):
        with patch.object(Setting, "_cached_value", return_value=None):
            self.assertEqual(
                Setting.get_run_summary_max_length(),
                Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH,
            )
        with patch.object(Setting, "_cached_value", return_value=""):
            self.assertEqual(
                Setting.get_run_summary_max_length(),
                Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH,
            )
        with patch.object(Setting, "_cached_value", return_value="80"):
            self.assertEqual(Setting.get_run_summary_max_length(), 80)
