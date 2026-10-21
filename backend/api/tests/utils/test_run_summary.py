from unittest.mock import patch

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
