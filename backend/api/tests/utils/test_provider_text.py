import json
from types import SimpleNamespace

from pydantic_ai.messages import TextPart, ThinkingPart
from pydantic_ai.models.google import GoogleModel

from ...utils import Constants
from ...utils.AiProviderFactory import _SpacingGoogleModel, build_pydantic_model
from ...utils.provider_text import join_provider_pieces, merge_text_parts, repair_wrapped_words
from ..TestCase import TestCase


def _google_provider():
    return SimpleNamespace(
        provider=Constants.AI_PROVIDER_GOOGLE,
        get_api_key=lambda: "test-key",
        resolve_model_name=lambda requested=None: "gemini-test",
    )


class ProviderTextJoinTests(TestCase):
    """Spaces dropped where Gemini splits a reply at a word boundary."""

    def test_parts_split_on_a_word_boundary_keep_the_space(self):
        pieces = [
            "automate your savings",
            "for financial peace of mind",
            "each day to",
            "handle your workload",
            "help with",
            "financial worries",
            "end of each day",
            "helps",
        ]
        # The old join is "".join, which is what pydantic-ai does with +=.
        self.assertEqual("".join(pieces[:2]), "automate your savingsfor financial peace of mind")
        self.assertEqual(
            join_provider_pieces(pieces[:2]),
            "automate your savings for financial peace of mind",
        )
        self.assertEqual(join_provider_pieces(pieces[2:4]), "each day to handle your workload")
        self.assertEqual(join_provider_pieces(pieces[4:6]), "help with financial worries")
        self.assertEqual(join_provider_pieces(pieces[6:]), "end of each day helps")

    def test_a_mid_word_boundary_currently_gets_a_space(self):
        """Conscious choice: both sides alphanumeric, including a split inside a word."""
        self.assertEqual(join_provider_pieces(["sav", "ings"]), "sav ings")

    def test_a_digit_boundary_gets_a_space(self):
        self.assertEqual(join_provider_pieces(["12", "34"]), "12 34")

    def test_a_newline_between_words_in_parsed_output_becomes_a_space(self):
        repaired = repair_wrapped_words(
            {
                "insights": [
                    {"text": "help with\nfinancial worries", "topic_key": "worry"},
                ]
            }
        )
        self.assertEqual(repaired["insights"][0]["text"], "help with financial worries")

    def test_merged_text_parts_parse_as_spaced_json(self):
        parts = merge_text_parts(
            [
                TextPart(content='{"text":"automate your savings'),
                TextPart(content='for financial peace of mind"}'),
                ThinkingPart(content="ignore"),
            ]
        )
        text_parts = [part.content for part in parts if isinstance(part, TextPart)]
        self.assertEqual(len(text_parts), 1)
        self.assertEqual(
            json.loads(text_parts[0])["text"],
            "automate your savings for financial peace of mind",
        )
        self.assertTrue(any(isinstance(part, ThinkingPart) for part in parts))

    def test_a_space_already_on_the_boundary_is_not_doubled(self):
        self.assertEqual(join_provider_pieces(["savings ", "for"]), "savings for")

    def test_chat_gets_plain_google_model_and_ask_gets_the_spacing_model(self):
        provider = _google_provider()
        plain, _settings = build_pydantic_model(provider)
        spaced, _spaced_settings = build_pydantic_model(provider, restore_part_spacing=True)
        self.assertIsInstance(plain, GoogleModel)
        self.assertNotIsInstance(plain, _SpacingGoogleModel)
        self.assertIsInstance(spaced, _SpacingGoogleModel)
