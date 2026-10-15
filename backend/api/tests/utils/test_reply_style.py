from django.test import SimpleTestCase

from ...utils.reply_style import normalise_reply, reply_ends_mid_sentence


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
