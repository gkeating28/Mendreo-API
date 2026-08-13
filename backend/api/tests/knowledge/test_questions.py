from unittest import mock

from rest_framework import status

from ..utils.BaseTest import BaseTest
from ...knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
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

    def test_create_slider_and_multi_select_controls(self):
        slider = self._create(
            {
                "prompt": "Mood check",
                "target_field": self.field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
                "flows": [Constants.KNOWLEDGE_FLOW_INITIAL],
                "order_by_flow": {"initial": 1},
                "value_labels": ["Low", "Alright", "Great"],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(slider.status_code, status.HTTP_201_CREATED, slider.json)
        self.assertEqual(slider.json["response_type"], "slider")
        self.assertEqual(slider.json["anchor_labels"], ["Struggling", "Thriving"])
        self.assertEqual(len(slider.json["value_labels"]), 11)

        multi = self._create(
            {
                "prompt": "Stressors",
                "target_field": self.field.id,
                "response_type": Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE,
                "suggested_responses": ["Work", "Family", "Money"],
                "min_selections": 1,
                "max_selections": 2,
                "flows": [Constants.KNOWLEDGE_FLOW_RETURN],
            },
            self.admin_one_access_token,
        )
        self.assertEqual(multi.status_code, status.HTTP_201_CREATED, multi.json)
        self.assertEqual(multi.json["min_selections"], 1)
        self.assertEqual(multi.json["max_selections"], 2)

    def test_list_includes_entry_count(self):
        question = KnowledgeQuestion.objects.create(
            prompt="How has sleep been?",
            target_field=self.field,
            active=True,
        )
        for value in ("restless", "better"):
            KnowledgeEntry.objects.create(
                consumer=self.consumer_one,
                field=self.field,
                value=value,
                source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
                knowledge_question=question,
            )
        deleted_entry = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.field,
            value="old",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
            knowledge_question=question,
        )
        deleted_entry.delete()

        listed = self._list(
            self.admin_one_access_token,
            {"target_field_id": self.field.id, "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        row = next(item for item in listed.json if item["id"] == question.id)
        self.assertEqual(row["entry_count"], 2)

        detail = self._get(question, self.admin_one_access_token)
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        self.assertEqual(detail.json["entry_count"], 2)

    def test_delete_cascades_to_linked_entries(self):
        question = KnowledgeQuestion.objects.create(
            prompt="How has sleep been?",
            target_field=self.field,
            active=True,
        )
        linked = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.field,
            value="restless",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
            knowledge_question=question,
        )
        unrelated = KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.field,
            value="cycling",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
        )

        deleted = self._delete(question, self.admin_one_access_token)
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(KnowledgeQuestion.objects.filter(id=question.id).exists())
        self.assertFalse(KnowledgeEntry.objects.filter(id=linked.id).exists())
        self.assertTrue(KnowledgeEntry.objects.filter(id=unrelated.id).exists())
        self.assertIsNotNone(KnowledgeEntry.all_objects.get(id=linked.id).deleted_at)
        self.assertIsNotNone(KnowledgeQuestion.all_objects.get(id=question.id).deleted_at)
        self.assertEqual(
            KnowledgeEntry.all_objects.get(id=linked.id).knowledge_question_id,
            question.id,
        )
