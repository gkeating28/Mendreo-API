import re
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ...agent.models import Agent
from ...message.debug_payload import step_guide_decision
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session, SessionStep
from ...setting.models import Setting
from ...utils import Constants
from ...utils.Agent import ExerciseStateResponse
from ...utils.extraction import (
    _DONE_WHEN_COVERAGE,
    _StepGuide,
    _StepGuideMissing,
    check_done_when,
    check_step_guide,
    instruction_lines,
    run_step_guide,
    schedule_step_guide,
)
from ...utils.turn_hint import goal_hint_text, merge_goal_and_step_guide, user_prompt_with_hint
from ..TestCase import TestCase
from ..utils.manager import Auth, General


class StepGuideTextTests(SimpleTestCase):
    def test_items_are_one_per_bullet_or_line(self):
        self.assertEqual(
            instruction_lines("- Ask where it shows up.\n- Ask when it started."),
            ["Ask where it shows up.", "Ask when it started."],
        )
        self.assertEqual(
            instruction_lines("1. Ask where it shows up.\n2) Ask when it started."),
            ["Ask where it shows up.", "Ask when it started."],
        )
        self.assertEqual(
            instruction_lines("Ask where it shows up. Then wait.\nAsk when it started."),
            ["Ask where it shows up. Then wait.", "Ask when it started."],
        )

    def test_a_one_paragraph_instruction_splits_into_sentences(self):
        self.assertEqual(
            instruction_lines("Ask where it shows up. Then wait for the answer."),
            ["Ask where it shows up.", "Then wait for the answer."],
        )
        self.assertEqual(
            instruction_lines("Ask this: what happened next. Then wait."),
            ["Ask this: what happened next.", "Then wait."],
        )
        self.assertEqual(
            instruction_lines("Ask about Dr. Smith. Then wait."),
            ["Ask about Dr. Smith.", "Then wait."],
        )
        self.assertEqual(
            instruction_lines("- Ask where it shows up. Then wait.\n- Ask when it started."),
            ["Ask where it shows up. Then wait.", "Ask when it started."],
        )

    def test_a_non_verbatim_instruction_is_dropped_and_a_failure_is_silent(self):
        step = type(
            "Step",
            (),
            {
                "instructions": "Ask where it shows up.\nAsk when it started.",
                "done_when": "A place and a time.",
            },
        )()
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction._step_transcript",
            return_value="User: somewhere.",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={"missing": "a time", "next_instruction": "Please ask when it started."},
        ) as ask:
            result = check_step_guide(None, step)
        self.assertEqual(ask.call_args.kwargs["temperature"], 0.1)
        prompt = ask.call_args.args[0]
        self.assertIn("Ask where it shows up.", prompt)
        self.assertIn("A place and a time.", prompt)
        self.assertIn(
            "next_instruction must be the first item that asks the assistant to ask or do "
            "something unconditionally and has not yet been done",
            prompt,
        )
        self.assertIn("must not be returned as next_instruction", prompt)
        self.assertIn("If only such items remain", prompt)
        self.assertEqual(result, {"missing": "a time", "next_instruction": ""})

        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction._step_transcript",
            return_value="",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={"missing": "", "next_instruction": "Ask   where it shows up."},
        ):
            kept = check_step_guide(None, step)
        self.assertEqual(kept["next_instruction"], "Ask where it shows up.")

        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction._step_transcript",
            return_value="",
        ), patch(
            "api.utils.extraction.AI.ask",
            side_effect=TimeoutError("timed out"),
        ), self.assertLogs("api.utils.extraction", level="DEBUG") as logged:
            self.assertIsNone(check_step_guide(None, step))
        self.assertTrue(any("step guide" in line.lower() for line in logged.output))

        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction.AI.ask",
        ) as ask:
            self.assertEqual(
                check_step_guide(None, type("Step", (), {"instructions": "  ", "done_when": ""})()),
                {"missing": "", "next_instruction": ""},
            )
        ask.assert_not_called()

    def test_a_conditional_item_is_not_returned_as_next_instruction(self):
        step = type(
            "Step",
            (),
            {
                "instructions": "If the user goes quiet, wait.\nAsk what happened.",
                "done_when": "What happened.",
            },
        )()
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction._step_transcript",
            return_value="User: nothing yet.",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={
                "missing": "what happened",
                "next_instruction": "If the user goes quiet, wait.",
            },
        ) as ask:
            result = check_step_guide(None, step)
        prompt = ask.call_args.args[0]
        self.assertIn("If the user goes quiet, wait.", prompt)
        self.assertIn("Ask what happened.", prompt)
        self.assertIn('they say "if", "when asked", "should the user..."', prompt)
        self.assertIn("tone, empathy, what not to discuss", prompt)
        self.assertIn("must not be returned as next_instruction", prompt)
        self.assertEqual(result, {"missing": "what happened", "next_instruction": ""})

    def _guide_call(self, *, next_instruction="Ask what happened."):
        step = type(
            "Step",
            (),
            {"instructions": "Ask what happened.", "done_when": "What happened."},
        )()
        with patch(
            "api.utils.extraction._step_transcript",
            return_value="User: nothing yet.",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={"missing": "what happened", "next_instruction": next_instruction},
        ) as ask:
            result = check_step_guide(None, step)
        return ask, result

    def test_the_guide_prompt_uses_the_done_when_coverage_wording(self):
        with override_settings(EXERCISE_STEP_GUIDE=True):
            ask, _result = self._guide_call()
        prompt = ask.call_args.args[0]
        self.assertIn(_DONE_WHEN_COVERAGE.strip(), prompt)
        self.assertIn(
            "Judge every part of Done when against the transcript and require all parts.",
            prompt,
        )
        self.assertIn(
            "When Done when asks for a count or a length, count literally and do not round up.",
            prompt,
        )
        self.assertIn(
            "A bare yes, no, or one-word reply to a question is not by itself a description "
            "or a rich answer unless Done when says otherwise.",
            prompt,
        )
        with patch(
            "api.utils.extraction._step_transcript",
            return_value="User: a named worry.",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={"met": False, "missing": "the plan"},
        ) as checker:
            check_done_when(None, type("Step", (), {"done_when": "A named worry and a plan."})())
        self.assertIn(_DONE_WHEN_COVERAGE.strip(), checker.call_args.args[0])
        self.assertIn(
            "missing must name only parts of DONE_WHEN that are not yet covered, and must never "
            "name an item from ITEMS, a rule about tone or wording, or anything that is not a part of DONE_WHEN.",
            prompt,
        )

    def test_next_instruction_is_omitted_when_that_flag_is_off(self):
        with override_settings(
            EXERCISE_STEP_GUIDE=True,
            EXERCISE_STEP_GUIDE_NEXT_INSTRUCTION=False,
        ):
            ask, result = self._guide_call()
        prompt = ask.call_args.args[0]
        self.assertIn(_DONE_WHEN_COVERAGE.strip(), prompt)
        self.assertNotIn("next_instruction", prompt)
        self.assertIs(ask.call_args.args[1], _StepGuideMissing)
        self.assertEqual(result, {"missing": "what happened", "next_instruction": ""})

    def test_next_instruction_flag_on_still_asks_for_it(self):
        with override_settings(
            EXERCISE_STEP_GUIDE=True,
            EXERCISE_STEP_GUIDE_NEXT_INSTRUCTION=True,
        ):
            ask, result = self._guide_call()
        prompt = ask.call_args.args[0]
        self.assertIs(ask.call_args.args[1], _StepGuide)
        self.assertIn("next_instruction must be the first item", prompt)
        self.assertIn(
            "An item is conditional when it applies only if the user says or does something in particular.",
            prompt,
        )
        self.assertIn("is not conditional", prompt)
        self.assertEqual(result["next_instruction"], "Ask what happened.")

    def test_if_in_the_middle_of_an_item_is_kept(self):
        kept = (
            "Ask them if they're spending much time actively worrying about it.",
            "Summarise the user's worry and ask them if you've got it right.",
        )
        cleared = (
            "If the user raises something later, note it.",
            "Explain what 'worry' is when asked: explain that worry is a thought.",
            "Should the user seem distressed, slow down.",
        )
        for item in kept:
            self.assertEqual(self._chosen(item), item)
        for item in cleared:
            self.assertEqual(self._chosen(item), "")

    def _chosen(self, item):
        step = type("Step", (), {"instructions": item, "done_when": "A named worry."})()
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction._step_transcript",
            return_value="",
        ), patch(
            "api.utils.extraction.AI.ask",
            return_value={"missing": "a worry", "next_instruction": item},
        ):
            result = check_step_guide(None, step)
        return result["next_instruction"]

    def test_the_guide_joins_the_rejection_hint_without_copying_it(self):
        goal = goal_hint_text("a place")
        merged = merge_goal_and_step_guide(goal, "a place", "Ask where it shows up.")
        self.assertIn(goal, merged)
        self.assertEqual(merged.count("This step is not done yet."), 1)
        self.assertIn("Next, do this from the step's instructions: Ask where it shows up.", merged)
        self.assertNotIn("Still to cover:", merged)
        self.assertIn("Ask about one part at a time.", merged)
        self.assertIn("continue with the next instruction", merged)
        self.assertNotIn("move on to the next part", merged)
        self.assertIsNone(re.search(r"\bready\b", merged.lower()))
        self.assertNotIn("next step", merged.lower())

        both = merge_goal_and_step_guide(goal, "the time of day", "Ask where it shows up.")
        self.assertEqual(both.count("This step is not done yet."), 1)
        self.assertEqual(both.count("Still to cover: the time of day."), 1)
        self.assertEqual(both.count("What is still missing: a place."), 1)

        self.assertIsNone(merge_goal_and_step_guide(None, "", ""))
        guide_only = merge_goal_and_step_guide(None, "", "Ask when it started.")
        self.assertTrue(guide_only.startswith("Next, do this from the step's instructions:"))
        self.assertNotIn("Still to cover:", guide_only)

    def test_the_debug_row_names_the_flag_and_whether_it_was_used(self):
        row = step_guide_decision(
            flag=True,
            missing="a place",
            next_instruction="Ask where it shows up.",
            used=True,
        )
        self.assertEqual(row["type"], "step_guide")
        self.assertTrue(row["fired"])
        self.assertEqual(
            row["inputs"],
            {
                "flag": True,
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "used": True,
            },
        )
        quiet = step_guide_decision(flag=True, missing="", next_instruction="", used=False)
        self.assertFalse(quiet["fired"])
        self.assertFalse(quiet["inputs"]["used"])


class StepGuideTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()

    def _live(self, *, step_no=1, exercise=True, instructions=None, done_when="A place and a time."):
        if not exercise:
            session = Session.objects.create(consumer=self.consumer)
            user, _agent = Participant.create_participants(session)
            return session, None, user
        exercise = General.create_exercise()
        step = exercise.steps.order_by("order").first()
        step.instructions = instructions or "Ask where it shows up.\nAsk when it started."
        step.done_when = done_when
        step.save(update_fields=["instructions", "done_when", "updated_at"])
        session = Session.objects.create(
            consumer=self.consumer,
            exercise=exercise,
            current_step_no=step_no,
            total_steps_no=exercise.steps_no or 1,
            state=Constants.SESSION_STATE_STEP_ACTIVE,
        )
        SessionStep.create(session, exercise)
        user, _agent = Participant.create_participants(session)
        return session, step, user

    def _user_message(self, session, user, text="It was yesterday afternoon."):
        return Message.objects.create(session=session, sender=user, text=text)

    def test_flag_off_makes_no_call_and_leaves_the_prompt_unchanged(self):
        session, _step, user = self._live()
        session.cached_prompt_meta = {
            "step_guide": {
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "step_no": 1,
            }
        }
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        message = self._user_message(session, user)
        with override_settings(EXERCISE_STEP_GUIDE=False), patch(
            "api.utils.extraction.AI.ask",
        ) as ask, patch(
            "api.utils.extraction._run_step_guide_in_background",
        ) as started:
            prompted = user_prompt_with_hint(session, message)
            schedule_step_guide(session)
        ask.assert_not_called()
        started.assert_not_called()
        self.assertEqual(prompted, message.text)
        self.assertIsNone(session.cached_prompt)
        session.refresh_from_db()
        self.assertEqual(
            session.cached_prompt_meta["step_guide"]["next_instruction"],
            "Ask where it shows up.",
        )

    def test_flag_on_stores_the_guide_and_the_next_turn_uses_it(self):
        session, _step, user = self._live()
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction.AI.ask",
            return_value={"missing": "a time", "next_instruction": "Ask when it started."},
        ):
            run_step_guide(session.id)
        session.refresh_from_db()
        stored = session.cached_prompt_meta["step_guide"]
        self.assertEqual(stored["missing"], "a time")
        self.assertEqual(stored["next_instruction"], "Ask when it started.")
        self.assertEqual(stored["step_no"], 1)

        capture = Setting.get_or_create_store_turn_prompts()
        capture.value = "true"
        capture.save()
        message = self._user_message(session, user)
        with override_settings(EXERCISE_STEP_GUIDE=True):
            prompted = user_prompt_with_hint(session, message)
        self.assertIn(
            "Next, do this from the step's instructions: Ask when it started.",
            prompted,
        )
        self.assertIn("Still to cover: a time.", prompted)
        self.assertIn(
            "If the user's latest message already covers this, continue with the next instruction.",
            prompted,
        )
        self.assertNotIn("move on to the next part", prompted)
        self.assertIsNone(re.search(r"\bready\b", prompted.lower()))
        self.assertTrue(prompted.rstrip().endswith("</TURN_HINT>"))
        session.refresh_from_db()
        self.assertNotIn("step_guide", session.cached_prompt_meta or {})
        self.assertIsNone(session.cached_prompt)
        noted = getattr(session, "_pending_turn_decisions")
        row = next(item for item in noted if item["type"] == "step_guide")
        self.assertTrue(row["inputs"]["flag"])
        self.assertTrue(row["inputs"]["used"])
        self.assertEqual(row["inputs"]["missing"], "a time")
        self.assertEqual(row["inputs"]["next_instruction"], "Ask when it started.")

    def test_a_failed_call_leaves_the_stored_guide_untouched(self):
        session, _step, _user = self._live()
        session.cached_prompt_meta = {
            "step_guide": {
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "step_no": 1,
            }
        }
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction.AI.ask",
            side_effect=ValueError("invalid json"),
        ):
            run_step_guide(session.id)
        session.refresh_from_db()
        self.assertEqual(
            session.cached_prompt_meta["step_guide"]["next_instruction"],
            "Ask where it shows up.",
        )

    def test_the_guide_combines_with_the_rejection_hint(self):
        session, _step, user = self._live()
        session.cached_prompt_meta = {
            "goal_hint": goal_hint_text("a place"),
            "step_guide": {
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "step_no": 1,
            },
        }
        session.save(update_fields=["cached_prompt_meta", "updated_at"])
        message = self._user_message(session, user)
        with override_settings(EXERCISE_STEP_GUIDE=True):
            prompted = user_prompt_with_hint(session, message)
        self.assertIn(goal_hint_text("a place"), prompted)
        self.assertEqual(prompted.count("This step is not done yet."), 1)
        self.assertIn("Ask where it shows up.", prompted)
        self.assertNotIn("Still to cover:", prompted)
        self.assertEqual(prompted.count("<TURN_HINT>"), 1)

    def test_the_next_instruction_clause_follows_its_own_flag(self):
        def prompted(flag):
            session, _step, user = self._live()
            session.cached_prompt_meta = {
                "step_guide": {
                    "missing": "a time",
                    "next_instruction": "Ask when it started.",
                    "step_no": 1,
                }
            }
            session.save(update_fields=["cached_prompt_meta", "updated_at"])
            message = self._user_message(session, user)
            with override_settings(
                EXERCISE_STEP_GUIDE=True,
                EXERCISE_STEP_GUIDE_NEXT_INSTRUCTION=flag,
            ):
                return user_prompt_with_hint(session, message)

        off = prompted(False)
        self.assertNotIn("Next, do this from the step's instructions:", off)
        self.assertIn("Still to cover: a time.", off)
        on = prompted(True)
        self.assertIn("Next, do this from the step's instructions: Ask when it started.", on)
        self.assertIn("Still to cover: a time.", on)

    def test_live_step_instructions_are_added_to_the_turn_hint_only_when_the_flag_is_on(self):
        from ...utils.turn_hint import _INSTRUCTIONS_LEAD

        self.assertEqual(
            _INSTRUCTIONS_LEAD,
            "Follow this step's instructions on this reply. "
            "An instruction that applies only if the user says or does something in particular "
            "(for example one that says if, when, or when asked) is to be done only when that happens, "
            "not on every reply:",
        )
        instructions = "Ask {{user.first_name}} where it shows up. Ask when it started."
        session, _step, user = self._live(instructions=instructions)
        message = self._user_message(session, user)
        with override_settings(EXERCISE_HINT_RESTATES_INSTRUCTIONS=False):
            off = user_prompt_with_hint(session, message)
        self.assertEqual(off, message.text)
        self.assertNotIn(_INSTRUCTIONS_LEAD, off)

        capture = Setting.get_or_create_store_turn_prompts()
        capture.value = "true"
        capture.save()
        name = (session.consumer.user.first_name or "").strip()
        with override_settings(EXERCISE_HINT_RESTATES_INSTRUCTIONS=True):
            alone = user_prompt_with_hint(session, message)
        self.assertEqual(alone.count("<TURN_HINT>"), 1)
        self.assertIn(_INSTRUCTIONS_LEAD, alone)
        self.assertIn("Ask when it started.", alone)
        self.assertNotIn("{{user.first_name}}", alone)
        if name:
            self.assertIn(name, alone)
        noted = getattr(session, "_pending_turn_decisions")
        hint = next(row for row in noted if row["type"] == "hint")
        self.assertTrue(hint["fired"])
        self.assertIn("The step instructions were added to the hint.", hint["what"])

        goal_session, _goal_step, goal_user = self._live(instructions=instructions)
        goal_session.cached_prompt_meta = {"goal_hint": goal_hint_text("a time")}
        goal_session.save(update_fields=["cached_prompt_meta", "updated_at"])
        goal_message = self._user_message(goal_session, goal_user)
        with override_settings(EXERCISE_HINT_RESTATES_INSTRUCTIONS=True):
            combined = user_prompt_with_hint(goal_session, goal_message)
        self.assertEqual(combined.count("<TURN_HINT>"), 1)
        self.assertIn(goal_hint_text("a time"), combined)
        self.assertIn(_INSTRUCTIONS_LEAD, combined)
        self.assertEqual(combined.count(_INSTRUCTIONS_LEAD), 1)

        guide_session, _guide_step, guide_user = self._live(
            instructions="Ask where it shows up. Ask when it started.",
        )
        guide_session.cached_prompt_meta = {
            "step_guide": {
                "missing": "a time",
                "next_instruction": "Ask where it shows up.",
                "step_no": 1,
            }
        }
        guide_session.save(update_fields=["cached_prompt_meta", "updated_at"])
        guide_message = self._user_message(guide_session, guide_user)
        with override_settings(
            EXERCISE_STEP_GUIDE=True,
            EXERCISE_HINT_RESTATES_INSTRUCTIONS=True,
        ):
            guided = user_prompt_with_hint(guide_session, guide_message)
        self.assertEqual(guided.count("<TURN_HINT>"), 1)
        self.assertIn("Still to cover: a time.", guided)
        self.assertEqual(guided.count("Ask where it shows up."), 1)
        self.assertIn("Ask when it started.", guided)
        self.assertIn(_INSTRUCTIONS_LEAD, guided)

        empty_session, empty_step, empty_user = self._live()
        empty_step.instructions = ""
        empty_step.save(update_fields=["instructions", "updated_at"])
        empty_message = self._user_message(empty_session, empty_user)
        with override_settings(EXERCISE_HINT_RESTATES_INSTRUCTIONS=True):
            empty = user_prompt_with_hint(empty_session, empty_message)
        self.assertEqual(empty, empty_message.text)
        self.assertNotIn(_INSTRUCTIONS_LEAD, empty)

        check_in, _check_step, check_user = self._live(step_no=0, instructions=instructions)
        check_message = self._user_message(check_in, check_user)
        general, _none, general_user = self._live(exercise=False)
        general_message = self._user_message(general, general_user)
        with override_settings(EXERCISE_HINT_RESTATES_INSTRUCTIONS=True):
            check_prompt = user_prompt_with_hint(check_in, check_message)
            general_prompt = user_prompt_with_hint(general, general_message)
        self.assertNotIn(_INSTRUCTIONS_LEAD, check_prompt)
        self.assertNotIn(_INSTRUCTIONS_LEAD, general_prompt)

    def test_check_in_and_general_chat_are_left_alone(self):
        check_in, _step, check_user = self._live(step_no=0)
        check_in.cached_prompt_meta = {
            "step_guide": {
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "step_no": 0,
            }
        }
        check_in.save(update_fields=["cached_prompt_meta", "updated_at"])
        check_message = self._user_message(check_in, check_user)
        general, _none, general_user = self._live(exercise=False)
        general.cached_prompt_meta = {
            "step_guide": {
                "missing": "a place",
                "next_instruction": "Ask where it shows up.",
                "step_no": 1,
            }
        }
        general.save(update_fields=["cached_prompt_meta", "updated_at"])
        general_message = self._user_message(general, general_user)
        with override_settings(EXERCISE_STEP_GUIDE=True), patch(
            "api.utils.extraction.AI.ask",
        ) as ask, patch(
            "api.utils.extraction._run_step_guide_in_background",
        ) as started:
            check_prompt = user_prompt_with_hint(check_in, check_message)
            general_prompt = user_prompt_with_hint(general, general_message)
            schedule_step_guide(check_in)
            schedule_step_guide(general)
        ask.assert_not_called()
        started.assert_not_called()
        self.assertEqual(check_prompt, check_message.text)
        self.assertNotIn("Next, do this from the step's instructions:", general_prompt)
        self.assertIsNone(getattr(check_in, "_pending_turn_decisions", None))
        self.assertIsNone(getattr(general, "_pending_turn_decisions", None))

    def test_the_reply_path_schedules_the_guide_and_does_not_call_the_model(self):
        session, _step, user = self._live()
        message = self._user_message(session, user, text="Here is one part of it.")
        reply = ExerciseStateResponse(
            text="Tell me one part of it.",
            reasoning="test",
            suggested_responses=[],
            question_kind="none",
            risk_level="none",
            step_goal_met=False,
            asks_readiness=False,
        )
        with patch(
            "api.utils.Agent.get_response",
            return_value=(reply, {}, None, None),
        ), patch(
            "api.utils.risk.apply_turn_risk",
            return_value=None,
        ), patch(
            "api.utils.extraction._run_step_guide_in_background",
        ) as started, patch(
            "api.utils.extraction.AI.ask",
        ) as ask:
            with override_settings(EXERCISE_STEP_GUIDE=False):
                Agent.get_response(session, message)
            started.assert_not_called()
            ask.assert_not_called()
            with override_settings(EXERCISE_STEP_GUIDE=True):
                Agent.get_response(session, message)
            ask.assert_not_called()
            started.assert_called_once_with(session.id)
