from rest_framework import status

from ..TestCase import TestCase
from ..utils.manager import Auth
from ...knowledge.models import KnowledgeEntry, KnowledgeField
from ...knowledge.services import (
    get_current_knowledge_summary,
    write_knowledge_entry,
)
from ...role.models import Role
from ...session.models import Session
from ...utils import Constants
from ...utils.Agent import _format_summary


class ConsumerKnowledgeProfileTests(TestCase):
    def setUp(self):
        self.admin = Auth.create_admin()
        self.admin_token = Auth.get_access_token(self.admin.user)
        self.consumer = Auth.create_consumer()

        self.sleep = KnowledgeField.objects.create(
            key="sleep_quality",
            label="Sleep quality",
            category="Wellbeing",
            active=True,
        )
        self.meds = KnowledgeField.objects.create(
            key="medication",
            label="Medication",
            category="Health",
            sensitive=True,
            active=True,
        )
        write_knowledge_entry(
            consumer=self.consumer,
            field=self.sleep,
            value="on and off",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
        )
        write_knowledge_entry(
            consumer=self.consumer,
            field=self.meds,
            value="sertraline",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
            confidence=0.8,
        )

    def test_get_profile_grouped_by_category(self):
        response = self._get(
            f"/consumers/{self.consumer.user_id}/knowledge",
            access_token=self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        categories = {c["category"]: c["fields"] for c in response.json["categories"]}
        self.assertIn("Wellbeing", categories)
        self.assertIn("Health", categories)

        sleep_row = next(r for r in categories["Wellbeing"] if r["field"]["key"] == "sleep_quality")
        self.assertEqual(sleep_row["value"], "on and off")
        self.assertEqual(sleep_row["source"], Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING)
        self.assertTrue(sleep_row["has_history"])

        meds_row = next(r for r in categories["Health"] if r["field"]["key"] == "medication")
        self.assertEqual(meds_row["value"], "sertraline")

    def test_profile_masks_sensitive_without_pii(self):
        limited = Auth.create_admin(email="viewer-know@example.com")
        limited.role = Role.get_admin()
        limited.save()
        perms = limited.role.permissions
        perms.pii = []
        perms.knowledge = ["view", "create", "edit"]
        perms.save()

        response = self._get(
            f"/consumers/{self.consumer.user_id}/knowledge",
            access_token=Auth.get_access_token(limited.user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        health = next(c for c in response.json["categories"] if c["category"] == "Health")
        meds_row = next(r for r in health["fields"] if r["field"]["key"] == "medication")
        self.assertEqual(meds_row["value"], Constants.KNOWLEDGE_RESTRICTED_PLACEHOLDER)
        self.assertTrue(meds_row["restricted"])

    def test_patch_appends_admin_entry_and_returns_profile(self):
        response = self._patch(
            f"/consumers/{self.consumer.user_id}/knowledge",
            {"field_id": self.sleep.id, "value": "much better"},
            access_token=self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(len(response.json["created"]), 1)
        self.assertEqual(response.json["created"][0]["source"], Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN)
        self.assertEqual(response.json["created"][0]["value"], "much better")

        current = KnowledgeEntry.current_for(self.consumer, self.sleep)
        self.assertEqual(current.value, "much better")
        self.assertEqual(
            KnowledgeEntry.objects.filter(consumer=self.consumer, field=self.sleep).count(),
            2,
        )

    def test_activity_feed_filter_by_source(self):
        response = self._get(
            f"/consumers/{self.consumer.user_id}/knowledge/activity",
            query_params_dict={"source": "question", "paginated": "false"},
            access_token=self.admin_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json)
        self.assertEqual(len(response.json), 1)
        self.assertEqual(response.json[0]["source"], Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION)
        self.assertEqual(response.json[0]["value"], "sertraline")

    def test_field_history_and_restricted_history(self):
        write_knowledge_entry(
            consumer=self.consumer,
            field=self.sleep,
            value="improving",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ADMIN,
            created_by=self.admin.user,
        )

        history = self._get(
            f"/consumers/{self.consumer.user_id}/knowledge/fields/{self.sleep.id}/history",
            query_params_dict={"paginated": "false"},
            access_token=self.admin_token,
        )
        self.assertEqual(history.status_code, status.HTTP_200_OK, history.json)
        self.assertFalse(history.json["restricted"])
        self.assertEqual(len(history.json["results"]), 2)
        self.assertEqual(history.json["results"][0]["value"], "improving")

        limited = Auth.create_admin(email="nopii-hist@example.com")
        limited.role = Role.get_admin()
        limited.save()
        perms = limited.role.permissions
        perms.pii = []
        perms.knowledge = ["view"]
        perms.save()

        restricted = self._get(
            f"/consumers/{self.consumer.user_id}/knowledge/fields/{self.meds.id}/history",
            query_params_dict={"paginated": "false"},
            access_token=Auth.get_access_token(limited.user),
        )
        self.assertEqual(restricted.status_code, status.HTTP_200_OK)
        self.assertTrue(restricted.json["restricted"])
        self.assertEqual(restricted.json["results"], [])

    def test_knowledge_summary_and_agent_prompt_include_knowledge(self):
        summary = get_current_knowledge_summary(self.consumer)
        self.assertIn("Sleep quality", summary)
        self.assertIn("on and off", summary)
        self.assertIn("sertraline", summary)

        formatted = _format_summary(self.consumer)
        self.assertIn("Structured knowledge about this user", formatted)
        self.assertIn("sleep_quality", formatted)

    def test_write_invalidates_session_prompt_cache(self):
        session = Session.objects.create(
            consumer=self.consumer,
            cached_prompt="stale prompt with old knowledge",
        )
        write_knowledge_entry(
            consumer=self.consumer,
            field=self.sleep,
            value="rested",
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_AI,
            confidence=0.7,
            session=session,
        )
        session.refresh_from_db()
        self.assertIsNone(session.cached_prompt)
