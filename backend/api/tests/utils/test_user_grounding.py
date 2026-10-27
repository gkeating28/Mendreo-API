from django.test import SimpleTestCase

from ...grounding.case_material import case_material_reason
from ...utils.user_grounding import grounded_in_user_words, keep_grounded_prose


class UserGroundingTests(SimpleTestCase):
    def test_a_vignette_is_not_the_users_words(self):
        said = "I'm fine"
        claim = "Amira feels socially isolated and sad about work."
        self.assertFalse(grounded_in_user_words(claim, said))
        self.assertEqual(keep_grounded_prose(claim, said), "")

    def test_a_paraphrase_of_the_users_words_stays(self):
        said = "I'll miss the deadline at work"
        claim = "Worried about the deadline at work."
        self.assertTrue(grounded_in_user_words(claim, said))
        mixed = f"{claim} Amira reported sadness and social isolation."
        kept = keep_grounded_prose(mixed, said)
        self.assertIn("deadline", kept)
        self.assertNotIn("Amira", kept)

    def test_case_material_matches_heading_and_dialogue(self):
        self.assertEqual(
            case_material_reason("Case Vignette: Amira", "She felt sad."),
            "case vignette",
        )
        self.assertEqual(case_material_reason("", "T: What happened?\nP: I panicked."), "session dialogue")
        self.assertEqual(case_material_reason("", "Kevin presented with worry."), "named patient story")
        self.assertIsNone(case_material_reason("Avoidance", "Avoidance keeps the cycle going."))
