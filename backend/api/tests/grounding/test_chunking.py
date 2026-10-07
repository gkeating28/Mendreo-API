from django.test import SimpleTestCase

from ...grounding.chunking import chunk_markdown, count_tokens, take_within_budget


class ChunkingTests(SimpleTestCase):
    def test_heading_path_and_single_chunk(self):
        pieces = chunk_markdown("# Module 3\n\n## Avoidance\n\nAvoidance keeps the cycle going.")
        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0].heading_path, "Module 3 > Avoidance")
        self.assertIn("cycle going", pieces[0].text)
        self.assertEqual(
            pieces[0].token_count,
            count_tokens(pieces[0].text) + count_tokens(pieces[0].heading_path),
        )

    def test_long_section_splits_with_overlap(self):
        body = " ".join(["avoidance"] * 900)
        pieces = chunk_markdown(f"# Module 3\n\n{body}")
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(piece.heading_path == "Module 3" for piece in pieces))
        self.assertTrue(all(piece.token_count <= 800 + count_tokens("Module 3") for piece in pieces))

    def test_budget_does_not_skip_a_smaller_later_chunk(self):
        chunks = [
            {"id": "a", "tokens": 800},
            {"id": "b", "tokens": 800},
            {"id": "c", "tokens": 100},
        ]
        chosen = take_within_budget(chunks, 4, 1500, lambda item: item["tokens"])
        self.assertEqual([item["id"] for item in chosen], ["a"])
