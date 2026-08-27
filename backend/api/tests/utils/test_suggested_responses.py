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
        self.assertIsNone(
            sanitize_suggested_responses(
                ["Can you explain", "How are you feeling?"],
                "Does that make sense?",
            )
        )

    def test_drops_chip_copied_from_agent_text(self):
        text = "Would evenings or weekends work better for you?"
        self.assertEqual(
            sanitize_suggested_responses(["Evenings", "weekends work better"], text),
            ["Evenings"],
        )

    def test_keeps_yes_no_offer_chips(self):
        self.assertEqual(
            sanitize_suggested_responses(["Yes", "No"], "Would you like to start?"),
            ["Yes", "No"],
        )

    def test_empty_and_none_passthrough(self):
        self.assertIsNone(sanitize_suggested_responses(None))
        self.assertEqual(sanitize_suggested_responses([]), [])


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
