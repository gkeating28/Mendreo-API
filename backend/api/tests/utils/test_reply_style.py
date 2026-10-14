from django.test import SimpleTestCase

from ...utils.reply_style import normalise_reply


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
