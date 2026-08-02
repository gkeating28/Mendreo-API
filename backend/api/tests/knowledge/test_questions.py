from unittest import mock

from rest_framework import status

from ..utils.BaseTest import BaseTest
from ...knowledge.models import KnowledgeField, KnowledgeQuestion
from ...utils import Constants


class KnowledgeQuestionTests(BaseTest):
    def endpoint(self):
        return "knowledge-questions"

    def setUp(self):
        super().setUp()
        self.field = KnowledgeField.objects.create(
            key="sleep_quality",
            label="Sleep quality",
            category="Wellbeing",
            active=True,
        )

    def test_admin_create_and_list(self):
        create = self._create(
            {
                "prompt": "How has your sleep been?",
                "target_field": self.field.id,
                "trigger": Constants.KNOWLEDGE_TRIGGER_FIRST_SESSION,
                "suggested_responses": ["Great", "Okay", "Poor"],
                "extraction_prompt": "Extract a short sleep quality summary.",
                "flows": [Constants.KNOWLEDGE_FLOW_INITIAL, Constants.KNOWLEDGE_FLOW_RETURN],
                "active": True,
            },
            self.admin_one_access_token,
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json)
        self.assertTrue(create.json["id"].startswith("knq_"))
        self.assertEqual(create.json["target_field"]["key"], "sleep_quality")
        self.assertEqual(create.json["trigger"], Constants.KNOWLEDGE_TRIGGER_FIRST_SESSION)

        listed = self._list(
            self.admin_one_access_token,
            {"target_field_id": self.field.id, "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listed.json), 1)

    def test_after_n_sessions_requires_n(self):
        response = self._create(
            {
                "prompt": "Check in",
                "target_field": self.field.id,
                "trigger": Constants.KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS,
                "trigger_config": {},
            },
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        ok = self._create(
            {
                "prompt": "Check in",
                "target_field": self.field.id,
                "trigger": Constants.KNOWLEDGE_TRIGGER_AFTER_N_SESSIONS,
                "trigger_config": {"n": 3},
            },
            self.admin_one_access_token,
        )
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED, ok.json)

    def test_test_extraction_dry_run(self):
        question = KnowledgeQuestion.objects.create(
            prompt="How has sleep been?",
            target_field=self.field,
            extraction_prompt="Summarise sleep quality in one word.",
            active=True,
        )

        with mock.patch("api.utils.AI.AI.ask") as ask:
            ask.return_value = {"value": "restless", "confidence": 0.9}
            response = self._post(
                f"/knowledge-questions/{question.id}/test-extraction",
                {"sample_reply": "I've been waking up a lot"},
                self.admin_one_access_token,
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(response.json["value"], "restless")
        self.assertEqual(response.json["confidence"], 0.9)
        self.assertEqual(response.json["target_field"]["key"], "sleep_quality")
        ask.assert_called_once()
