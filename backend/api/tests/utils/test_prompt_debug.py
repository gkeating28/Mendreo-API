"""Prompt debug is read-only: same reply, admin-only, sourced from the live constants."""

from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework import status

from ...exercise.pre_exercise import CHECK_IN_RULES
from ...message.models import TurnPrompt
from ...session.models import Session
from ...utils import Constants
from ...utils.Agent import DESCRIPTION_PREFIX, STEP_SCOPE_RULES, ExerciseStateResponse
from ...utils.prompt_debug import (
    build_debug,
    catalogue,
    finish_debug,
    reply_style_report,
)
from ...utils.reply_style import normalise_reply
from ..utils.BaseTest import BaseTest
from ..utils.manager import General

_OPENING_TEXT = "Welcome. This is the test opening."
_ROOT = Path(__file__).resolve().parents[4]


def _fake_opening(session, consumer_message):
    from ...utils.prompt_debug import capture_on, remember_reply, remember_turn

    if capture_on():
        remember_turn(
            system_prompt="SYSTEM PROMPT",
            user_prompt=consumer_message.text,
            model_name="gemini-test",
            retrieval_enabled=False,
            schema=ExerciseStateResponse,
        )
        remember_reply(_OPENING_TEXT, _OPENING_TEXT)
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


def _ai_payload(*_args, **_kwargs):
    return {"text": "rewritten", "met": True, "missing": "", "risk_level": "low"}


class PromptDebugUnitTests(SimpleTestCase):
    def test_catalogue_reads_the_live_constant(self):
        rows = {row["label"]: row for row in catalogue()}
        programming = rows["programming_instructions"]
        self.assertEqual(programming["text"], Constants.PROMPT_PROGRAMMING_INSTRUCTIONS)
        self.assertEqual(programming["applies"], "every turn")
        self.assertEqual(rows["step_scope_rules"]["text"], STEP_SCOPE_RULES)
        self.assertEqual(rows["step_scope_rules"]["applies"], "exercise only")
        self.assertEqual(rows["description_prefix"]["text"], DESCRIPTION_PREFIX)
        self.assertEqual(rows["onboarding_followup_rules"]["applies"], "general chat only")
        self.assertEqual(rows["check_in_rules"]["text"], CHECK_IN_RULES)
        self.assertEqual(rows["check_in_rules"]["applies"], "check-in only")
        self.assertIn("Ask the first question of step 1 now.", rows["hidden_opener"]["text"])
        included = build_debug(
            system_prompt=STEP_SCOPE_RULES + "\n" + DESCRIPTION_PREFIX,
            user_prompt="The exercise has already been introduced during the check-in. Ask the first question of step 1 now. Do not welcome the user, explain the exercise, or ask if it is right for them.",
        )
        labels = [row["label"] for row in included["blocks"]]
        self.assertIn("step_scope_rules", labels)
        self.assertIn("description_prefix", labels)
        self.assertIn("hidden_opener", labels)
        self.assertNotIn("check_in_rules", labels)
        source = (_ROOT / programming["file"]).read_text().splitlines()
        self.assertTrue(
            source[programming["line"] - 1].startswith("PROMPT_PROGRAMMING_INSTRUCTIONS")
        )

    def test_reply_style_report_does_not_change_the_reply(self):
        raw = "Thanks for sharing that. The color is blue."
        cleaned = normalise_reply(raw)
        report = reply_style_report(raw, cleaned)
        self.assertEqual(normalise_reply(raw), cleaned)
        self.assertEqual(cleaned, "The colour is blue.")
        self.assertTrue(report["changed"])
        self.assertEqual(report["rules"], ["spelling", "opening strip"])

        plain = "What is the thought?"
        self.assertEqual(normalise_reply(plain), plain)
        self.assertEqual(
            reply_style_report(plain, plain),
            {"changed": False, "rules": []},
        )
        dashed = normalise_reply("Wait\u2014really?")
        self.assertEqual(dashed, "Wait - really?")
        self.assertEqual(reply_style_report("Wait\u2014really?", dashed)["rules"], ["dash"])

    def test_check_in_rules_are_listed_when_the_test_prompt_omits_them(self):
        short = "You are starting a pre-exercise check-in."
        debug = build_debug(
            system_prompt=None,
            user_prompt=short,
            extra_block_labels=("check_in_rules",),
        )
        self.assertNotIn("Conduct a short conversational check-in only.", short)
        rules = next(row for row in debug["blocks"] if row["label"] == "check_in_rules")
        self.assertEqual(rules["text"], CHECK_IN_RULES)
        self.assertEqual(debug["retrieved_chunks"], [])

    def test_retrieved_chunks_are_titles_and_source_ids_only(self):
        user_prompt = "<RETRIEVED>\nTitle: Form 10.1\nThe full chunk text stays here.\n</RETRIEVED>"
        debug = build_debug(
            system_prompt="system",
            user_prompt=user_prompt,
            retrieval_enabled=True,
            pending=[{"source_id": "ksrc_1"}],
        )
        self.assertEqual(
            debug["retrieved_chunks"],
            [{"title": "Form 10.1", "source_id": "ksrc_1"}],
        )
        self.assertNotIn("full chunk text", str(debug["retrieved_chunks"]))
        self.assertTrue(debug["retrieval_enabled"])

    def test_finish_debug_reads_goal_and_depth_without_keeping_them(self):
        session = type("Session", (), {"cached_prompt_meta": {}})()
        session._debug_goal_missing = "the worry itself"
        session._debug_depth_held = True

        class Cap:
            data = {
                "system_prompt": "system",
                "user_prompt": "user\n\n<TURN_HINT>\nAsk one more question.\n</TURN_HINT>",
                "retrieval_enabled": False,
                "reply_before": "What is the thought?",
                "reply_after": "What is the thought?",
            }

        debug = finish_debug(Cap(), session, refusal_reason="not in readiness yes-list")
        self.assertEqual(debug["goal_missing"], "the worry itself")
        self.assertTrue(debug["depth_gate_held"])
        self.assertEqual(debug["refusal_reason"], "not in readiness yes-list")
        self.assertEqual(debug["turn_hint"], "Ask one more question.")
        self.assertFalse(debug["reply_style"]["changed"])
        self.assertFalse(hasattr(session, "_debug_goal_missing"))
        self.assertFalse(hasattr(session, "_debug_depth_held"))


class PromptDebugApiTests(BaseTest):
    def endpoint(self):
        return "exercises"

    def setUp(self):
        self._resend = patch("resend.Emails.send", return_value={"id": "email_test"})
        self._ask = patch("api.utils.AI.AI.ask", side_effect=_ai_payload)
        self._model = patch("api.utils.Agent.get_response", side_effect=_fake_opening)
        self._resend.start()
        self._ask.start()
        self._model.start()
        try:
            super().setUp()
        except Exception:
            self._stop()
            raise

    def tearDown(self):
        self._stop()
        super().tearDown()

    def _stop(self):
        self._model.stop()
        self._ask.stop()
        self._resend.stop()

    def _draft(self):
        exercise = General.create_exercise()
        exercise.status = Constants.EXERCISE_STATUS_DRAFT
        exercise.save(update_fields=["status", "updated_at"])
        return exercise

    def test_non_admin_gets_no_debug(self):
        exercise = self._draft()
        response = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": self.consumer_one.user_id},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn("debug", response.json)
        self.assertNotIn(b"system_prompt", response.content)

        rules = self._get(
            "/exercises/prompt-rules",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(rules.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn(b"programming_instructions", rules.content)
        self.assertNotIn(b"system_prompt", rules.content)

    def test_debug_does_not_change_the_reply(self):
        exercise = self._draft()
        prompts_before = TurnPrompt.objects.count()
        started = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": self.consumer_one.user_id},
            self.admin_one_access_token,
        )
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
        self.assertEqual(started.json["opening_message"], _OPENING_TEXT)
        self.assertEqual(started.json["debug"]["system_prompt"], "SYSTEM PROMPT")
        self.assertEqual(started.json["debug"]["model_name"], "gemini-test")
        self.assertNotEqual(started.json["debug"]["system_prompt"], started.json["opening_message"])

        session_id = started.json["session_id"]
        sent = self._post(
            f"/exercises/{exercise.id}/test-runs/{session_id}/messages",
            {"text": "I keep thinking I will fail."},
            self.admin_one_access_token,
        )
        self.assertEqual(sent.status_code, status.HTTP_200_OK, sent.json)
        self.assertEqual(sent.json["text"], _OPENING_TEXT)
        self.assertEqual(sent.json["user_message"]["text"], "I keep thinking I will fail.")
        self.assertIn("debug", sent.json)
        self.assertFalse(sent.json["debug"]["reply_style"]["changed"])
        self.assertIsNone(sent.json["debug"]["refusal_reason"])
        self.assertEqual(TurnPrompt.objects.count(), prompts_before)
        self.assertEqual(sent.json["debug"]["system_prompt"], "SYSTEM PROMPT")

    def test_typed_refusal_names_the_reason_and_keeps_the_reply(self):
        exercise = self._draft()
        started = self._post(
            f"/exercises/{exercise.id}/test-runs",
            {"consumer_id": self.consumer_one.user_id},
            self.admin_one_access_token,
        )
        self.assertEqual(started.status_code, status.HTTP_200_OK, started.json)
        session = Session.objects.get(id=started.json["session_id"])
        session.state = Constants.SESSION_STATE_AWAITING_READY
        session.save(update_fields=["state", "updated_at"])

        typed = "I want to stay with this a bit longer."
        sent = self._post(
            f"/exercises/{exercise.id}/test-runs/{session.id}/messages",
            {"text": typed},
            self.admin_one_access_token,
        )
        self.assertEqual(sent.status_code, status.HTTP_200_OK, sent.json)
        self.assertEqual(sent.json["text"], typed)
        self.assertEqual(sent.json["debug"]["refusal_reason"], "not in readiness yes-list")
        self.assertFalse(sent.json["debug"]["depth_gate_held"])

    def test_admin_catalogue_matches_the_constants(self):
        response = self._get(
            "/exercises/prompt-rules",
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        rows = {row["label"]: row for row in response.json}
        self.assertEqual(rows["programming_instructions"]["text"], Constants.PROMPT_PROGRAMMING_INSTRUCTIONS)
        self.assertEqual(rows["check_in_rules"]["text"], CHECK_IN_RULES)
        self.assertEqual(rows["pending_question"]["applies"], "every turn")
        self.assertNotIn("system_prompt", response.json[0])
