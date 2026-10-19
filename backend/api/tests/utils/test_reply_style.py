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

    def test_reframing_offer_leaves_the_worry_step(self):
        instructions = (
            "Name the Worry\n"
            "Ask the user what they're worried about. "
            "Ask them if they're spending much time actively worrying about it. "
            "Ask them about specific behaviours that they do while worrying."
        )
        reply = (
            "Team meetings and client presentations can definitely be high-stakes situations. "
            'To help you build confidence, we\'ll work on a technique called "reframing." '
            "It's about shifting your perspective on challenging situations. "
            "Are you ready to give it a try?"
        )
        self.assertTrue(reply_leaves_the_step(reply, instructions))
        curly = reply.replace('"reframing."', "\u201creframing.\u201d")
        self.assertTrue(reply_leaves_the_step(curly, instructions))

    def test_step_one_can_still_summarise_and_close(self):
        instructions = (
            "Name the Worry\n"
            "Ask the user what they're worried about. "
            "Ask them if they're spending much time actively worrying about it. "
            "Ask the user to use less judgmental and more factual language. "
            "Summarise the user's worry and ask them if you've got it right."
        )
        self.assertFalse(
            reply_leaves_the_step(
                "Let's try that in more factual words. What happened in the meeting?",
                instructions,
            )
        )
        summary = (
            "You're worried about freezing in team meetings and client presentations, "
            "and you rehearse what you'll say. Have I got that right?"
        )
        self.assertFalse(reply_leaves_the_step(summary, instructions))
        self.assertFalse(
            reply_leaves_the_step(
                "Are you ready for the next step?",
                instructions,
            )
        )
        factual = (
            "Put more factually, you have a presentation on Thursday and you keep "
            "rewriting the opening. Have I got that right?"
        )
        self.assertFalse(reply_leaves_the_step(factual, instructions))

    def test_the_next_worry_question_stays_on_the_step(self):
        instructions = (
            "Ask the user what they're worried about. "
            "Ask them if they're spending much time actively worrying about it."
        )
        self.assertFalse(
            reply_leaves_the_step(
                "Team meetings can be high-stakes. How much time are you spending worrying about them?",
                instructions,
            )
        )

    def test_a_start_line_in_the_step_does_not_allow_reframing(self):
        instructions = "Let's start by asking what they are worried about."
        self.assertTrue(
            reply_leaves_the_step(
                'We\'ll work on a technique called "reframing." Are you ready to give it a try?',
                instructions,
            )
        )

    def test_reframe_step_may_use_that_word(self):
        instructions = (
            "Reframe the thought\n"
            "Ask them to rewrite it in a more factual, less judgmental way."
        )
        self.assertFalse(
            reply_leaves_the_step(
                "Reframe that thought so it is more factual. What would you say instead?",
                instructions,
            )
        )

    def test_a_technique_the_step_names_may_be_used(self):
        instructions = (
            'Explain the technique called "alternative action" and ask what they would do instead.'
        )
        self.assertFalse(
            reply_leaves_the_step(
                'This step uses a technique called "alternative action." '
                "What would you do instead of worrying?",
                instructions,
            )
        )

    def test_an_unnamed_called_technique_leaves_the_step(self):
        self.assertTrue(
            reply_leaves_the_step(
                'There is a method called "thought defusion" we can use.',
                "Ask what they are worried about.",
            )
        )

    def test_another_exercise_in_the_step_does_not_allow_a_different_opening(self):
        instructions = "An alternative action could be another exercise in the app."
        self.assertFalse(
            reply_leaves_the_step(
                "You could use another exercise in the app when you are at your desk.",
                instructions,
            )
        )
        self.assertTrue(
            reply_leaves_the_step(
                "This exercise will guide you to notice your thoughts without judgment.",
                instructions,
            )
        )

    def test_off_script_hold_drops_the_technique_and_readiness(self):
        from ...utils.Agent import _hold_on_step

        class Reply:
            text = 'We\'ll work on a technique called "reframing." Are you ready to give it a try?'
            suggested_responses = ["Yes", "Not yet"]
            question_kind = "readiness"
            asks_readiness = True
            step_goal_met = True
            is_step_complete = True

        reply = Reply()
        _hold_on_step(reply)
        self.assertNotIn("refram", reply.text.lower())
        self.assertTrue(reply.text.endswith("?"))
        self.assertEqual(reply.suggested_responses, [])
        self.assertEqual(reply.question_kind, "open")
        self.assertFalse(reply.asks_readiness)
        self.assertFalse(reply.step_goal_met)
        self.assertFalse(reply.is_step_complete)

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
