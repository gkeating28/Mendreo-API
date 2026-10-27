"""Prompt debug is read-only: same reply, admin-only, sourced from the live constants."""

import string
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework import status

from ...exercise.pre_exercise import CHECK_IN_RULES
from ...message.models import TurnPrompt
from ...session.models import Session
from ...utils import Constants
from django.core.cache import cache

from ...setting.models import Setting
from ...utils.Agent import (
    STEP_SCOPE_RULES,
    ExerciseStateResponse,
    _prompt_template,
    _step_already_started,
    apply_style_instructions,
    is_bare_opening,
    style_instructions_stale,
)
from ...utils.SessionStateMachine import (
    HIDDEN_OPENER_GREET_REPEAT,
    HIDDEN_OPENER_START,
    greeting_text,
    opening_turn,
)

_LENGTH_OVERRIDE = (
    "If this step's instructions ask for a longer reply, such as a summary, "
    "that overrides the reply-length line above."
)
from ...utils.prompt_debug import (
    build_debug,
    catalogue,
    finish_debug,
    reply_style_report,
)
from ...utils.reply_style import normalise_reply, stay_on_step_catalogue_text
from ...utils.summary_prompts import (
    DEFAULT_RUN_SUMMARY_PROMPT,
    DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT,
    DEFAULT_UPDATE_SUMMARY_PROMPT,
)
from ...utils.turn_hint import ON_STEP_FALLBACK, STAY_ON_STEP_HINT
from ..TestCase import TestCase
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
        self.assertEqual(
            rows["step_scope_rules"]["applies"],
            "exercise only; the first-message sentence is omitted "
            "on the no-check-in opening turn",
        )
        self.assertNotIn("virtual AI Therapist", programming["text"])
        self.assertNotIn("Maintain a calm, warm, and professional tone.", programming["text"])
        self.assertNotIn("Be confident, concise and assertive.", programming["text"])
        self.assertNotIn("<FEEDBACK>", programming["text"])
        self.assertNotIn("<ASSETS>", programming["text"])
        self.assertIn("trained on the Unified Protocol", programming["text"])
        self.assertIn("supporting your client through therapeutic conversations", programming["text"])
        self.assertIn("or 'It sounds like'", programming["text"])
        self.assertEqual(programming["text"].count("Never thank the user for sharing"), 1)
        self.assertEqual(programming["text"].count("Never open with 'Thanks for sharing'"), 1)
        self.assertNotIn("weigh evidence for or against a thought or worry", rows["step_scope_rules"]["text"])
        self.assertNotIn("0 to 10 scale", rows["step_scope_rules"]["text"])
        self.assertNotIn("balanced or more accurate thought", rows["step_scope_rules"]["text"])
        self.assertNotIn("brainstorm solutions", rows["step_scope_rules"]["text"])
        self.assertIn(
            "Your first message must be the first question in those instructions.",
            rows["step_scope_rules"]["text"],
        )
        self.assertIn("ask if you have it right", rows["step_scope_rules"]["text"])
        self.assertIn(_LENGTH_OVERRIDE, rows["step_scope_rules"]["text"])
        self.assertIn(
            "you may ask whether they are ready for the next step",
            rows["step_scope_rules"]["text"],
        )
        fallback = rows["on_step_fallback"]
        self.assertEqual(fallback["text"], ON_STEP_FALLBACK)
        self.assertIn(
            "Answer in two sentences from <CLIENT_SUMMARY>",
            rows["about_the_user_hint"]["text"],
        )
        self.assertIn(
            "a client block has something to name",
            rows["about_the_user_hint"]["applies"],
        )
        self.assertEqual(
            fallback["applies"],
            "replaces the model's reply when an off-script retry still leaves the step",
        )
        self.assertTrue(fallback["file"].endswith("turn_hint.py"))
        fallback_source = (_ROOT / fallback["file"]).read_text().splitlines()
        self.assertTrue(fallback_source[fallback["line"] - 1].startswith("ON_STEP_FALLBACK"))
        guard = rows["stay_on_step_guard"]
        self.assertEqual(guard["text"], stay_on_step_catalogue_text())
        self.assertTrue(guard["text"].startswith(STAY_ON_STEP_HINT))
        self.assertIn("retries once", guard["text"])
        self.assertTrue(guard["file"].endswith("reply_style.py"))
        guard_source = (_ROOT / guard["file"]).read_text().splitlines()
        self.assertIn("def reply_leaves_the_step", guard_source[guard["line"] - 1])
        self.assertEqual(rows["client_summary_prompt"]["text"], DEFAULT_UPDATE_SUMMARY_PROMPT)
        self.assertEqual(
            rows["client_summary_prompt"]["applies"],
            "editable in Settings (update_summary)",
        )
        self.assertEqual(
            rows["exercise_summary_prompt"]["text"],
            DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT,
        )
        self.assertEqual(
            rows["exercise_summary_prompt"]["applies"],
            "editable in Settings (update_exercise_summary)",
        )
        self.assertNotIn("description_prefix", rows)
        self.assertNotIn("2 sentences", rows["programming_instructions"]["text"])
        self.assertNotIn("compound questions", rows["programming_instructions"]["text"])
        self.assertEqual(
            rows["reply_length"]["text"],
            Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION,
        )
        self.assertEqual(rows["reply_length"]["applies"], "editable in Settings (reply_length)")
        self.assertEqual(
            rows["one_question"]["text"],
            Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
        )
        self.assertEqual(rows["one_question"]["applies"], "editable in Settings (one_question)")
        self.assertEqual(
            rows["client_knowledge_rule"]["text"],
            Constants.DEFAULT_CLIENT_KNOWLEDGE_RULE,
        )
        self.assertEqual(
            rows["client_knowledge_rule"]["applies"],
            "editable in Settings (client_knowledge_rule)",
        )
        self.assertEqual(rows["run_summary_prompt"]["text"], DEFAULT_RUN_SUMMARY_PROMPT)
        self.assertEqual(
            rows["run_summary_prompt"]["applies"],
            "editable in Settings (run_summary_prompt)",
        )
        self.assertNotIn("restructuring_rewrite", rows)
        self.assertEqual(rows["onboarding_followup_rules"]["applies"], "general chat only")
        self.assertIn("One question only. Two sentences max.", rows["onboarding_followup_rules"]["text"])
        self.assertIn("PHASE stay_on_opener", rows["onboarding_followup_rules"]["text"])
        self.assertIn("PHASE permission", rows["onboarding_followup_rules"]["text"])
        self.assertIn("PHASE followup", rows["onboarding_followup_rules"]["text"])
        self.assertNotIn("do not run a daily check-in", rows["onboarding_followup_rules"]["text"])
        self.assertNotIn("do not offer an exercise", rows["onboarding_followup_rules"]["text"])
        self.assertNotIn("Do not also check in or triage", rows["onboarding_followup_rules"]["text"])
        self.assertEqual(rows["check_in_rules"]["text"], CHECK_IN_RULES)
        self.assertEqual(rows["check_in_rules"]["applies"], "check-in only")
        self.assertIn("Ask the first question of step 1 now.", rows["hidden_opener"]["text"])
        self.assertIn(HIDDEN_OPENER_START, rows["hidden_opener"]["text"])
        self.assertIn("No-check-in step-1 open", rows["hidden_opener"]["text"])
        self.assertIn("no-check-in step-1 open", rows["hidden_opener"]["applies"])
        included = build_debug(
            system_prompt=(
                STEP_SCOPE_RULES
                + "\n"
                + Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION
                + "\n"
                + Constants.DEFAULT_ONE_QUESTION_INSTRUCTION
            ),
            user_prompt="The exercise has already been introduced during the check-in. Ask the first question of step 1 now. Do not welcome the user, explain the exercise, or ask if it is right for them.",
        )
        labels = [row["label"] for row in included["blocks"]]
        self.assertIn("step_scope_rules", labels)
        self.assertIn("reply_length", labels)
        self.assertIn("one_question", labels)
        self.assertIn("hidden_opener", labels)
        self.assertNotIn("description_prefix", labels)
        self.assertNotIn("check_in_rules", labels)
        self.assertNotIn("greet me and explain", rows["hidden_opener"]["text"])
        source = (_ROOT / programming["file"]).read_text().splitlines()
        self.assertTrue(
            source[programming["line"] - 1].startswith("PROMPT_PROGRAMMING_INSTRUCTIONS")
        )

    def test_style_lines_come_from_settings_and_a_blank_omits_them(self):
        base = Constants.PROMPT_PROGRAMMING_INSTRUCTIONS.format(
            user_name="Sam",
            client_knowledge_rule="client-knowledge-rule",
            up_technique_rule="rule",
        )
        self.assertNotIn("2 sentences", base)
        self.assertNotIn("compound questions", base)
        filled = apply_style_instructions(
            base,
            Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION,
            Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
        )
        self.assertLess(
            filled.index("no more than 2 sentences"),
            filled.index("When explaining a concept"),
        )
        self.assertLess(
            filled.index("compound questions"),
            filled.index("Always refer to Sam"),
        )
        blank = apply_style_instructions(base, "", "   ")
        self.assertEqual(blank, base)
        self.assertFalse(
            style_instructions_stale(
                filled,
                Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION,
                Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
            )
        )
        self.assertTrue(
            style_instructions_stale(
                filled,
                "",
                Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
            )
        )
        custom = "Keep replies to one short sentence"
        self.assertTrue(
            style_instructions_stale(
                filled,
                custom,
                Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
            )
        )
        rewritten = apply_style_instructions(
            base,
            custom,
            "",
        )
        self.assertIn(custom, rewritten)
        self.assertNotIn("compound questions", rewritten)
        self.assertFalse(style_instructions_stale(rewritten, custom, ""))

    def test_bare_opening_omits_the_two_lines(self):
        self.assertTrue(is_bare_opening(False, 1, False))
        self.assertFalse(is_bare_opening(True, 1, False))
        self.assertFalse(is_bare_opening(False, 1, True))
        self.assertFalse(is_bare_opening(False, 2, False))

        opening = _step_already_started(1, 3, bare_opening=True)
        later = _step_already_started(1, 3, bare_opening=False)
        step_two = _step_already_started(2, 3, bare_opening=False)
        self.assertNotIn("Do not write a welcome", opening)
        self.assertNotIn("Your first message must be the first question", opening)
        self.assertIn("Do only what this step's instructions tell you to do", opening)
        self.assertIn(_LENGTH_OVERRIDE, opening)
        self.assertIn("Do not write a welcome", later)
        self.assertIn("Your first message must be the first question", later)
        self.assertIn("Do not introduce the exercise", step_two)
        self.assertIn("Your first message must be the first question", step_two)
        self.assertNotIn("Do not write a welcome", step_two)

        fresh = SimpleNamespace(
            in_pre_exercise_phase=lambda: False,
            current_step_no=1,
        )
        self.assertEqual(greeting_text(fresh), HIDDEN_OPENER_START)
        check_in = SimpleNamespace(
            in_pre_exercise_phase=lambda: True,
            current_step_no=0,
        )
        self.assertEqual(greeting_text(check_in), HIDDEN_OPENER_GREET_REPEAT)
        self.assertEqual(greeting_text(fresh, opening_turn(1)), opening_turn(1))

    def test_length_override_is_in_the_exercise_prompt_only(self):
        def filled(template, **overrides):
            names = {
                field
                for _, field, _, _ in string.Formatter().parse(template)
                if field
            }
            values = {name: "" for name in names}
            values.update(overrides)
            return template.format(**values)

        exercise = filled(
            _prompt_template(SimpleNamespace(exercise=object())),
            exercise_steps=_step_already_started(1, 3),
        )
        general = filled(_prompt_template(SimpleNamespace(exercise=None)))
        self.assertIn(_LENGTH_OVERRIDE, exercise)
        self.assertNotIn(_LENGTH_OVERRIDE, general)

    def test_missing_style_setting_uses_the_default_and_a_blank_drops_it(self):
        rows = {}

        def get_or_create(key, defaults):
            if key not in rows:
                rows[key] = SimpleNamespace(value=defaults["value"])
                return rows[key], True
            return rows[key], False

        cache.clear()
        with patch.object(Setting.objects, "get_or_create", side_effect=get_or_create):
            self.assertEqual(
                Setting.get_reply_length_instruction(),
                Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION,
            )
            self.assertEqual(
                Setting.get_one_question_instruction(),
                Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
            )
            self.assertEqual(
                rows[Constants.SETTING_KEY_REPLY_LENGTH].value,
                Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION,
            )
            self.assertEqual(
                rows[Constants.SETTING_KEY_ONE_QUESTION].value,
                Constants.DEFAULT_ONE_QUESTION_INSTRUCTION,
            )

            rows[Constants.SETTING_KEY_REPLY_LENGTH].value = ""
            rows[Constants.SETTING_KEY_ONE_QUESTION].value = "   "
            cache.clear()
            self.assertEqual(Setting.get_reply_length_instruction(), "")
            self.assertEqual(Setting.get_one_question_instruction(), "")
            self.assertEqual(
                apply_style_instructions("base\n- Always refer to ", "", ""),
                "base\n- Always refer to ",
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
        self.assertFalse(debug["on_step_retried"])
        self.assertFalse(debug["on_step_held"])

    def test_on_step_retry_debug_uses_the_retried_hint(self):
        user_prompt = f"What is the worry?\n\n<TURN_HINT>\n{STAY_ON_STEP_HINT}\n</TURN_HINT>"
        debug = build_debug(
            system_prompt="system",
            user_prompt=user_prompt,
            on_step_retried=True,
            on_step_held=True,
        )
        self.assertEqual(debug["user_prompt"], user_prompt)
        self.assertEqual(debug["turn_hint"], STAY_ON_STEP_HINT)
        self.assertTrue(debug["on_step_retried"])
        self.assertTrue(debug["on_step_held"])
        labels = [row["label"] for row in debug["blocks"]]
        self.assertIn("stay_on_step_guard", labels)
        held = finish_debug(
            type("Cap", (), {"data": {
                "system_prompt": "system",
                "user_prompt": user_prompt,
                "on_step_retried": True,
                "on_step_held": False,
            }})(),
            type("Session", (), {"cached_prompt_meta": {}})(),
        )
        self.assertTrue(held["on_step_retried"])
        self.assertFalse(held["on_step_held"])
        self.assertEqual(held["turn_hint"], STAY_ON_STEP_HINT)


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
        response = TestCase._get(
            "/exercises/prompt-rules",
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        rows = {row["label"]: row for row in response.json}
        self.assertEqual(rows["programming_instructions"]["text"], Constants.PROMPT_PROGRAMMING_INSTRUCTIONS)
        self.assertEqual(rows["reply_length"]["text"], Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION)
        self.assertIn("editable in Settings (reply_length)", rows["reply_length"]["applies"])
        self.assertEqual(rows["one_question"]["text"], Constants.DEFAULT_ONE_QUESTION_INSTRUCTION)
        self.assertIn("editable in Settings (one_question)", rows["one_question"]["applies"])
        self.assertEqual(
            rows["client_knowledge_rule"]["text"],
            Constants.DEFAULT_CLIENT_KNOWLEDGE_RULE,
        )
        self.assertIn(
            "editable in Settings (client_knowledge_rule)",
            rows["client_knowledge_rule"]["applies"],
        )
        self.assertNotIn("restructuring_rewrite", rows)
        self.assertNotIn("description_prefix", rows)
        self.assertEqual(rows["check_in_rules"]["text"], CHECK_IN_RULES)
        self.assertEqual(rows["pending_question"]["applies"], "every turn")
        self.assertEqual(rows["on_step_fallback"]["text"], ON_STEP_FALLBACK)
        self.assertIn(
            "Answer in two sentences from <CLIENT_SUMMARY>",
            rows["about_the_user_hint"]["text"],
        )
        self.assertIn(
            "a client block has something to name",
            rows["about_the_user_hint"]["applies"],
        )
        self.assertEqual(rows["step_scope_rules"]["text"], STEP_SCOPE_RULES)
        self.assertNotIn("virtual AI Therapist", rows["programming_instructions"]["text"])
        self.assertNotIn("<FEEDBACK>", rows["programming_instructions"]["text"])
        self.assertNotIn("<ASSETS>", rows["programming_instructions"]["text"])
        self.assertNotIn("weigh evidence for or against a thought or worry", rows["step_scope_rules"]["text"])
        self.assertIn(
            "Your first message must be the first question in those instructions.",
            rows["step_scope_rules"]["text"],
        )
        self.assertEqual(rows["client_summary_prompt"]["text"], DEFAULT_UPDATE_SUMMARY_PROMPT)
        self.assertIn("editable in Settings", rows["exercise_summary_prompt"]["applies"])
        self.assertNotIn("system_prompt", response.json[0])
