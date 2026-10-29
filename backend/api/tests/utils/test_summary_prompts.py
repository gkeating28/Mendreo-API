from django.test import SimpleTestCase

from ...utils.summary_prompts import (
    DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT,
    DEFAULT_UPDATE_SUMMARY_PROMPT,
    client_summary_prompt,
    exercise_summary_prompt,
    stored_instruction,
)


class SummaryPromptTests(SimpleTestCase):
    def test_name_is_filled_and_session_data_is_added(self):
        prompt = client_summary_prompt(
            DEFAULT_UPDATE_SUMMARY_PROMPT,
            "Michael",
            "<Session>today</Session>",
            "old notes",
            "old observations",
            "old steps",
        )
        self.assertIn("continuous summary of your client Michael.", prompt)
        self.assertIn("The summary covers Michael from their first session up to today.", prompt)
        self.assertNotIn("{name}", prompt)
        self.assertIn("<NEW_SESSIONS>\n<Session>today</Session>\n</NEW_SESSIONS>", prompt)
        self.assertIn("<PREVIOUS_SUMMARY>\nold notes\n</PREVIOUS_SUMMARY>", prompt)
        self.assertIn("<PREVIOUS_OBSERVATIONS>\nold observations\n</PREVIOUS_OBSERVATIONS>", prompt)
        self.assertIn("<PREVIOUS_NEXT_STEPS>\nold steps\n</PREVIOUS_NEXT_STEPS>", prompt)

    def test_a_blank_instruction_uses_the_default(self):
        self.assertEqual(
            stored_instruction("  ", DEFAULT_UPDATE_SUMMARY_PROMPT, "Sam"),
            DEFAULT_UPDATE_SUMMARY_PROMPT.replace("{name}", "Sam"),
        )

    def test_exercise_summary_keeps_the_stored_wording_and_the_results(self):
        prompt = exercise_summary_prompt(
            "Notes for {name}.",
            "Michael",
            "felt tense",
            "Name the Worry: deadlines",
            "previous plan",
        )
        self.assertTrue(prompt.startswith("Notes for Michael."))
        self.assertIn("Check-in summary:\nfelt tense", prompt)
        self.assertIn("Step results:\nName the Worry: deadlines", prompt)
        self.assertIn("Previous notes:\nprevious plan", prompt)
        self.assertIn("Use only what the user said in their own messages.", prompt)
        self.assertNotIn(DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT, prompt)
