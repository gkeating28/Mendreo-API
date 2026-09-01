from django.test import SimpleTestCase

from ...utils.StepProgress import (
    is_advance_gate_text,
    is_progress_confirm_text,
    resolve_step_progress,
)


class AdvanceGateTests(SimpleTestCase):
    def test_next_step_asks_are_gates(self):
        self.assertTrue(is_advance_gate_text("Are you ready to progress to the next step?"))
        self.assertTrue(is_advance_gate_text("Are you ready to move on?"))
        self.assertTrue(is_advance_gate_text("Shall we move on to the next step?"))
        self.assertTrue(
            is_advance_gate_text(
                "How do you think all or nothing thinking might have affected your thought? "
                "Once you've reflected on that, are you ready to move on?"
            )
        )

    def test_mid_step_ready_to_proceed_is_not_a_gate(self):
        self.assertFalse(is_advance_gate_text("Are you ready to proceed?"))
        self.assertFalse(
            is_advance_gate_text("I've shortened that thought. Are you ready to proceed?")
        )

    def test_confirms(self):
        self.assertTrue(is_progress_confirm_text("Yes"))
        self.assertTrue(is_progress_confirm_text("ok"))
        self.assertTrue(is_progress_confirm_text("I'm ready"))
        self.assertFalse(is_progress_confirm_text("It made me see things as failure"))
        self.assertFalse(is_progress_confirm_text("No"))


class ResolveStepProgressTests(SimpleTestCase):
    def test_does_not_force_complete_when_model_jumps_step_no(self):
        step, complete = resolve_step_progress(
            current_step_no=1,
            total_steps_no=3,
            tagged_step_no=2,
            is_step_complete=False,
            agent_text="Let's look at thinking traps.",
            user_text="I'll fail the meeting",
            last_agent_text="What thought is looping?",
        )
        self.assertEqual(step, 1)
        self.assertFalse(complete)

    def test_rejects_complete_without_a_prior_gate(self):
        step, complete = resolve_step_progress(
            current_step_no=1,
            total_steps_no=3,
            tagged_step_no=2,
            is_step_complete=True,
            agent_text="Let's look at thinking traps.",
            user_text="All or nothing thinking",
            last_agent_text="Could this be a thinking trap?",
        )
        self.assertEqual(step, 1)
        self.assertFalse(complete)

    def test_rejects_complete_on_the_same_turn_as_the_ask(self):
        _, complete = resolve_step_progress(
            current_step_no=2,
            total_steps_no=3,
            tagged_step_no=2,
            is_step_complete=True,
            agent_text="Are you ready to progress to the next step?",
            user_text="I rephrased the thought",
            last_agent_text="Try saying it without the trap.",
        )
        self.assertFalse(complete)

    def test_honors_complete_after_gate_and_yes(self):
        step, complete = resolve_step_progress(
            current_step_no=2,
            total_steps_no=3,
            tagged_step_no=2,
            is_step_complete=True,
            agent_text="Great, we'll challenge it next.",
            user_text="Yes",
            last_agent_text="Are you ready to progress to the next step?",
        )
        self.assertEqual(step, 2)
        self.assertTrue(complete)

    def test_forces_complete_after_gate_and_yes_when_model_forgets_the_flag(self):
        step, complete = resolve_step_progress(
            current_step_no=1,
            total_steps_no=3,
            tagged_step_no=2,
            is_step_complete=False,
            agent_text="Let's name the thinking trap that showed up.",
            user_text="Yes, ready to continue",
            last_agent_text="Are you ready to move on to the next step?",
        )
        self.assertEqual(step, 1)
        self.assertTrue(complete)

    def test_last_step_does_not_need_a_gate(self):
        _, complete = resolve_step_progress(
            current_step_no=3,
            total_steps_no=3,
            tagged_step_no=3,
            is_step_complete=True,
            agent_text="Here's a summary of what we covered.",
            user_text="I could live with it",
            last_agent_text="If it were true, could you live with it?",
        )
        self.assertTrue(complete)

    def test_skip_still_completes(self):
        step, complete = resolve_step_progress(
            current_step_no=1,
            total_steps_no=3,
            tagged_step_no=1,
            is_step_complete=True,
            agent_text="Step Auto Skipped",
            user_text="qa skip step",
            last_agent_text="What thought is looping?",
            is_skip=True,
        )
        self.assertEqual(step, 1)
        self.assertTrue(complete)
