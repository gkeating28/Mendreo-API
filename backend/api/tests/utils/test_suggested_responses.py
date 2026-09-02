from django.test import SimpleTestCase

from ...utils.SuggestedResponses import sanitize_suggested_responses
from ...utils.ExerciseOffer import format_agent_offer


class SanitizeSuggestedResponsesTests(SimpleTestCase):
    def test_drops_question_restatement_of_scheduling_prompt(self):
        text = (
            "Great. Let's schedule a specific time to work on the project and another "
            "time to check your status update. When would work best for you to do these?"
        )
        self.assertIsNone(
            sanitize_suggested_responses(["When can you work?"], text)
        )

    def test_keeps_answers_and_follow_ups(self):
        self.assertEqual(
            sanitize_suggested_responses(
                ["Tonight", "This weekend", "Tell me more", "I don't understand"],
                "When would evenings or weekends work?",
            ),
            ["Tonight", "This weekend", "Tell me more"],
        )

    def test_keeps_how_about_and_what_about_proposals(self):
        self.assertEqual(
            sanitize_suggested_responses(
                ["How about tonight", "What about mornings"],
                "When would work best for you?",
            ),
            ["How about tonight", "What about mornings"],
        )

    def test_drops_can_you_and_how_are_you_chips(self):
        self.assertEqual(
            sanitize_suggested_responses(
                ["Can you explain", "How are you feeling?"],
                "Does that make sense?",
            ),
            ["Yes", "No", "Not sure"],
        )

    def test_drops_chip_copied_from_agent_text(self):
        text = "Would evenings or weekends work better for you?"
        self.assertEqual(
            sanitize_suggested_responses(["Evenings", "weekends work better"], text),
            ["Evenings"],
        )

    def test_keeps_numbered_choices_listed_in_the_prompt(self):
        text = (
            'Looking at your thought, "The future is hopeless," could it be influenced by: '
            "1) All or nothing thinking, 2) Jumping to conclusions, or 3) Neither?"
        )
        self.assertEqual(
            sanitize_suggested_responses(["Neither of these"], text),
            [
                "All or nothing thinking",
                "Jumping to conclusions",
                "Neither",
            ],
        )

    def test_extracts_numbered_choices_when_chips_are_missing(self):
        text = (
            "Could it be: 1) All or nothing thinking, 2) Jumping to conclusions, or 3) Neither?"
        )
        self.assertEqual(
            sanitize_suggested_responses(None, text),
            [
                "All or nothing thinking",
                "Jumping to conclusions",
                "Neither",
            ],
        )

    def test_extracts_quoted_inline_choices_when_chips_are_stripped(self):
        text = (
            "Does your thought, 'I am going to fail in my career,' feel influenced by "
            "'all or nothing thinking,' 'jumping to conclusions,' or neither of these?"
        )
        self.assertEqual(
            sanitize_suggested_responses(None, text),
            [
                "All or nothing thinking",
                "Jumping to conclusions",
                "Neither of these",
            ],
        )
        self.assertEqual(
            sanitize_suggested_responses(["Neither of these"], text),
            [
                "All or nothing thinking",
                "Jumping to conclusions",
                "Neither of these",
            ],
        )

    def test_extracts_a_or_b_or_neither_without_a_choice_lead(self):
        text = "Does this feel like a, or b or neither?"
        self.assertEqual(
            sanitize_suggested_responses(None, text),
            ["A", "B", "Neither"],
        )
        self.assertEqual(
            sanitize_suggested_responses(
                None,
                "Could this be: a) All or nothing thinking, b) Jumping to conclusions, or neither?",
            ),
            ["All or nothing thinking", "Jumping to conclusions", "Neither"],
        )

    def test_ignores_apostrophes_in_lets_and_well(self):
        text = (
            "Let's look at your target thought: 'I am going to fail in my career.' "
            "We'll challenge this thought now. Do you know for certain that this is true?"
        )
        self.assertEqual(
            sanitize_suggested_responses(["Yes", "No"], text),
            ["Yes", "No"],
        )
        self.assertEqual(
            sanitize_suggested_responses(None, text),
            ["Yes", "No", "Not sure"],
        )

    def test_drops_agent_voice_and_garbled_prompt_chips(self):
        text = (
            "Let's start the challenges now. Do you know for certain that this is true?"
        )
        self.assertEqual(
            sanitize_suggested_responses(
                ["Lets start the challenges is now the option"],
                text,
            ),
            ["Yes", "No", "Not sure"],
        )
        self.assertEqual(
            sanitize_suggested_responses(
                ["Lets start the challenges is now the option", "Yes", "No"],
                text,
            ),
            ["Yes", "No"],
        )

    def test_closing_question_offers_finish_not_yes_no(self):
        text = (
            "That is great progress. Do you have any further questions, "
            "or are you ready to end the exercise?"
        )
        self.assertEqual(
            sanitize_suggested_responses(None, text),
            ["I have a question", "I'm ready to finish"],
        )

    def test_does_not_treat_ordinary_questions_as_choice_lists(self):
        text = "Would evenings or weekends work better for you?"
        self.assertEqual(
            sanitize_suggested_responses(["Evenings", "This weekend"], text),
            ["Evenings", "This weekend"],
        )
        self.assertEqual(
            sanitize_suggested_responses(["Yes", "No"], "Would you like to start?"),
            ["Yes", "No"],
        )

    def test_empty_and_none_passthrough(self):
        self.assertIsNone(sanitize_suggested_responses(None))
        self.assertEqual(sanitize_suggested_responses([]), [])

    def test_drops_ready_to_start_on_open_worry_prompt(self):
        text = (
            "To get started, please tell me specifically what you are worried "
            "about right now."
        )
        self.assertIsNone(
            sanitize_suggested_responses(["I'm ready to start"], text)
        )
        self.assertIsNone(
            sanitize_suggested_responses(["I'm ready to start", "Let's start"], text)
        )

    def test_keeps_start_chip_on_explicit_start_invite(self):
        text = "Would you like to start this exercise?"
        self.assertEqual(
            sanitize_suggested_responses(["I'm ready to start", "Not now"], text),
            ["I'm ready to start", "Not now"],
        )

    def test_drops_ready_to_continue_on_problem_solving_prompt(self):
        text = (
            "You have described what's worrying you. Sometimes this can be tough! "
            "Now let's figure out what to do about it..."
        )
        self.assertIsNone(
            sanitize_suggested_responses(["Yes, ready to continue"], text)
        )


class FormatAgentOfferSanitizeTests(SimpleTestCase):
    def test_strips_question_chips_when_not_an_exercise_offer(self):
        response = type("R", (), {})()
        response.text = (
            "Great. Let's schedule a specific time to work on the project. "
            "When would work best for you to do these?"
        )
        response.suggested_responses = ["When can you work?", "Tonight"]
        session = type("S", (), {"exercise_id": None})()

        chips, text = format_agent_offer(response, exercise=None, session=session)
        self.assertEqual(chips, ["Tonight"])
        self.assertEqual(text, response.text)
