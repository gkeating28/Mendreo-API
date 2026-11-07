from rest_framework import status

from ...prompt.models import PromptVersion
from ...utils import Constants
from ...utils.prompt_blocks import ensure_prompt_versions
from ..TestCase import TestCase
from ..utils.manager import Auth


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


class InsightsPromptListTests(TestCase):
    def test_list_seeds_insight_versions_once(self):
        token = Auth.get_platform_admin_access_token()
        keys = (
            (
                Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION,
                Constants.DEFAULT_INSIGHTS_INSTRUCTION,
            ),
            (
                Constants.PROMPT_KEY_INSIGHTS_TONE_GUIDE,
                Constants.DEFAULT_INSIGHTS_TONE_GUIDE,
            ),
        )
        for key, body in keys:
            self.assertEqual(PromptVersion.objects.filter(key=key).count(), 0)
            response = self._get(f"/prompts/{key}/versions", access_token=token)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
            versions = response.json["versions"]
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["version"], 1)
            self.assertTrue(versions[0]["active"])
            self.assertEqual(versions[0]["body"], body)
            self.assertEqual(response.json["key"], key)

            again = self._get(f"/prompts/{key}/versions", access_token=token)
            self.assertEqual(again.status_code, status.HTTP_200_OK, again.json)
            self.assertEqual(len(again.json["versions"]), 1)
            self.assertEqual(again.json["versions"][0]["id"], versions[0]["id"])
            self.assertEqual(PromptVersion.objects.filter(key=key).count(), 1)

        missing = self._get("/prompts/not-a-prompt/versions", access_token=token)
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing.json, {"message": "Object not found"})
        self.assertEqual(PromptVersion.objects.filter(key="not-a-prompt").count(), 0)

    def test_list_does_not_add_v1_when_a_later_version_exists(self):
        token = Auth.get_platform_admin_access_token()
        key = Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION
        existing = PromptVersion.objects.create(
            key=key,
            body="Already written.",
            version=2,
            active=True,
        )
        response = self._get(f"/prompts/{key}/versions", access_token=token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(
            [row["version"] for row in response.json["versions"]],
            [2],
        )
        self.assertEqual(response.json["versions"][0]["id"], existing.id)
        self.assertFalse(PromptVersion.objects.filter(key=key, version=1).exists())
        self.assertEqual(PromptVersion.objects.filter(key=key).count(), 1)
