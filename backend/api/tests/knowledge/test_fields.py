from rest_framework import status

from ..utils.BaseTest import BaseTest
from ...knowledge.models import KnowledgeField
from ...utils import Constants


class KnowledgeFieldTests(BaseTest):
    def endpoint(self):
        return "knowledge-fields"

    def _results(self, response):
        if isinstance(response.json, dict) and "results" in response.json:
            return response.json["results"]
        return response.json

    def test_admin_can_create_list_and_filter(self):
        create = self._create(
            {
                "key": "sleep_quality",
                "label": "Sleep quality",
                "category": "Wellbeing",
                "value_type": Constants.KNOWLEDGE_VALUE_TYPE_TEXT,
                "sensitive": False,
                "active": True,
            },
            self.admin_one_access_token,
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertTrue(create.json["id"].startswith("knf_"))
        self.assertEqual(create.json["key"], "sleep_quality")

        KnowledgeField.objects.create(
            key="medication",
            label="Medication",
            category="Health",
            sensitive=True,
            active=False,
        )

        listed = self._list(
            self.admin_one_access_token,
            {"category": "Wellbeing", "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        keys = [row["key"] for row in self._results(listed)]
        self.assertIn("sleep_quality", keys)
        self.assertNotIn("medication", keys)

        inactive = self._list(
            self.admin_one_access_token,
            {"active": "false", "paginated": "false"},
        )
        inactive_keys = [row["key"] for row in self._results(inactive)]
        self.assertIn("medication", inactive_keys)

    def test_duplicate_key_rejected(self):
        payload = {
            "key": "mood",
            "label": "Mood",
            "category": "Wellbeing",
        }
        first = self._create(payload, self.admin_one_access_token)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self._create(payload, self.admin_one_access_token)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_consumer_forbidden(self):
        response = self._create(
            {"key": "x", "label": "X"},
            self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_edit_and_delete(self):
        field = KnowledgeField.objects.create(key="stress", label="Stress", category="Wellbeing")
        patched = self._update(field, {"label": "Stress level"}, self.admin_one_access_token)
        self.assertEqual(patched.status_code, status.HTTP_200_OK)
        self.assertEqual(patched.json["label"], "Stress level")

        deleted = self._delete(field, self.admin_one_access_token)
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(KnowledgeField.objects.filter(id=field.id).exists())
