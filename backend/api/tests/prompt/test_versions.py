from ...prompt.models import PromptVersion
from ...utils import Constants
from ...utils.prompt_blocks import ensure_prompt_versions
from ..TestCase import TestCase


class InsightsPromptTests(TestCase):
    def test_insight_prompts_are_seeded(self):
        chosen = ensure_prompt_versions()

        instruction = chosen[Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION]
        tone = chosen[Constants.PROMPT_KEY_INSIGHTS_TONE_GUIDE]
        self.assertEqual(instruction.version, 1)
        self.assertTrue(instruction.active)
        self.assertEqual(instruction.body, Constants.DEFAULT_INSIGHTS_INSTRUCTION)
        self.assertEqual(tone.version, 1)
        self.assertTrue(tone.active)
        self.assertEqual(tone.body, Constants.DEFAULT_INSIGHTS_TONE_GUIDE)

        again = ensure_prompt_versions()
        self.assertEqual(again[Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION].id, instruction.id)
        self.assertEqual(
            PromptVersion.objects.filter(key=Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION).count(),
            1,
        )
        self.assertEqual(
            PromptVersion.objects.filter(key=Constants.PROMPT_KEY_INSIGHTS_TONE_GUIDE).count(),
            1,
        )
