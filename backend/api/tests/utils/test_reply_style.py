from django.test import SimpleTestCase

from ...utils.reply_style import (
    normalise_reply,
    reply_ends_mid_sentence,
    reply_leaves_the_step,
)


class ReplyStyleTests(SimpleTestCase):
    def test_dashes_spaces_and_american_spellings_are_rewritten(self):
        text = (
            "You have strategies in place\u2014like planning\u2014and you've recognized it. "
            "A calm\u2003behavior helps."
        )
        cleaned = normalise_reply(text)
        self.assertNotIn("\u2014", cleaned)
        self.assertNotIn("\u2003", cleaned)
        self.assertIn("recognised", cleaned)
        self.assertIn("behaviour", cleaned)
        self.assertIn(" - ", cleaned)
        self.assertIsNone(normalise_reply(None))

    def test_mid_sentence_replies_are_detected(self):
        self.assertTrue(reply_ends_mid_sentence("Thanks for sharing. The thought of"))
        self.assertTrue(reply_ends_mid_sentence("We've just walked through the "))
        self.assertFalse(reply_ends_mid_sentence("What do you notice?"))
        self.assertFalse(reply_ends_mid_sentence("You named the worry."))
        self.assertFalse(reply_ends_mid_sentence("Well done!"))
        self.assertFalse(reply_ends_mid_sentence("You said 'I'll mess up'."))
        self.assertFalse(reply_ends_mid_sentence(""))
        self.assertFalse(reply_ends_mid_sentence(None))

    def test_starting_another_exercise_leaves_the_step(self):
        instructions = "Ask the user what they're worried about."
        self.assertTrue(
            reply_leaves_the_step(
                "Let's start with a short exercise to help you observe your thoughts. Are you ready to begin?",
                instructions,
            )
        )
        self.assertTrue(
            reply_leaves_the_step(
                "This exercise will guide you to notice your thoughts without judgment.",
                instructions,
            )
        )
        self.assertFalse(
            reply_leaves_the_step(
                "What are you worried about?",
                instructions,
            )
        )

    def test_a_step_that_starts_an_activity_may_say_so(self):
        instructions = "Let's start with a short exercise: ask them to notice one breath."
        self.assertFalse(
            reply_leaves_the_step(
                "Let's start with a short exercise. Notice one breath.",
                instructions,
            )
        )

    def test_banned_openings_are_removed(self):
        self.assertEqual(
            normalise_reply("Thanks for sharing. What is the worry?"),
            "What is the worry?",
        )
        self.assertEqual(
            normalise_reply(
                "Thanks for sharing. It sounds like meetings are hard. What happens next?"
            ),
            "What happens next?",
        )
        self.assertEqual(
            normalise_reply("Thank you for sharing that. Name one worry."),
            "Name one worry.",
        )
        self.assertEqual(normalise_reply("Thanks for sharing."), "Thanks for sharing.")
        self.assertEqual(
            normalise_reply("You said it sounds like a lot. What is one part of it?"),
            "You said it sounds like a lot. What is one part of it?",
        )
