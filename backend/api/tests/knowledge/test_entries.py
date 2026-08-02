from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import Auth
from ...knowledge.models import KnowledgeEntry, KnowledgeField
from ...role.models import Role
from ...utils import Constants


class KnowledgeEntryTests(BaseTest):
    def endpoint(self):
        return "knowledge-entries"

    def setUp(self):
        super().setUp()
        self.field = KnowledgeField.objects.create(
            key="medication",
            label="Medication",
            category="Health",
            sensitive=True,
            active=True,
        )
        self.public_field = KnowledgeField.objects.create(
            key="hobby",
            label="Hobby",
            category="Lifestyle",
            sensitive=False,
            active=True,
        )

    def test_admin_create_entry(self):
        response = self._create(
            {
                "consumer": self.consumer_one.user_id,
                "field": self.public_field.id,
                "value": "cycling",
                "confidence": 1.0,
            },
            self.admin_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.assertEqual(response.json["source"], Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN)
        self.assertEqual(response.json["value"], "cycling")
        self.assertTrue(response.json["id"].startswith("kne_"))

    def test_sensitive_value_masked_without_pii(self):
        KnowledgeEntry.objects.create(
            consumer=self.consumer_one,
            field=self.field,
            value="sertraline",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
            confidence=1.0,
        )

        # Super Admin has pii:view — should see real value
        with_pii = self._list(
            self.admin_one_access_token,
            {"consumer_id": self.consumer_one.user_id, "paginated": "false"},
        )
        self.assertEqual(with_pii.status_code, status.HTTP_200_OK)
        sensitive_row = next(r for r in with_pii.json if r["field"]["key"] == "medication")
        self.assertEqual(sensitive_row["value"], "sertraline")

        # Admin role without pii — should see Restricted
        limited_admin = Auth.create_admin(email="nopii@example.com")
        limited_admin.role = Role.get_admin()
        limited_admin.save()
        # Ensure Admin role has knowledge view but no pii
        perms = limited_admin.role.permissions
        perms.pii = []
        perms.knowledge = ["view", "create", "edit"]
        perms.save()

        token = Auth.get_access_token(limited_admin.user)
        masked = self._list(
            token,
            {"consumer_id": self.consumer_one.user_id, "paginated": "false"},
        )
        self.assertEqual(masked.status_code, status.HTTP_200_OK, masked.json)
        sensitive_row = next(r for r in masked.json if r["field"]["key"] == "medication")
        self.assertEqual(sensitive_row["value"], Constants.KNOWLEDGE_RESTRICTED_PLACEHOLDER)
