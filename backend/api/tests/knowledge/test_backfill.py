from ..utils.BaseTest import BaseTest
from ...attribute.models import Attribute
from ...knowledge.models import KnowledgeEntry, KnowledgeField
from ...knowledge.services import backfill_knowledge_from_onboarding
from ...question.models import Question
from ...tasks import backfill_knowledge_from_onboarding as backfill_task
from ...utils import Constants


class KnowledgeBackfillTests(BaseTest):
    def endpoint(self):
        return "knowledge-entries"

    def test_backfill_creates_entries_from_onboarding_attributes(self):
        field = KnowledgeField.objects.create(
            key="sleep_quality",
            label="Sleep quality",
            category="Wellbeing",
            active=True,
        )
        question = Question.objects.create(
            type=Constants.QUESTION_TYPE_TEXT,
            title="How is sleep?",
            attribute_key="sleep_quality",
            survey=False,
            order=1,
        )
        attribute = Attribute.objects.create(
            consumer=self.consumer_one,
            question=question,
            key="sleep_quality",
            value="on and off",
        )

        # Unmatched attribute (no field)
        other_q = Question.objects.create(
            type=Constants.QUESTION_TYPE_TEXT,
            title="Other",
            attribute_key="unmapped_key",
            survey=False,
            order=2,
        )
        Attribute.objects.create(
            consumer=self.consumer_one,
            question=other_q,
            key="unmapped_key",
            value="x",
        )

        result = backfill_knowledge_from_onboarding()
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["unmatched"], 1)

        entry = KnowledgeEntry.objects.get(attribute=attribute)
        self.assertEqual(entry.field_id, field.id)
        self.assertEqual(entry.value, "on and off")
        self.assertEqual(entry.source, Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING)

        # Idempotent
        result_again = backfill_knowledge_from_onboarding()
        self.assertEqual(result_again["created"], 0)
        self.assertEqual(result_again["skipped"], 1)
        self.assertEqual(KnowledgeEntry.objects.filter(attribute=attribute).count(), 1)

    def test_celery_task_wrapper(self):
        KnowledgeField.objects.create(key="mood", label="Mood", active=True)
        question = Question.objects.create(
            type=Constants.QUESTION_TYPE_NUMBER,
            title="Mood?",
            attribute_key="mood",
            survey=False,
            order=1,
        )
        Attribute.objects.create(
            consumer=self.consumer_one,
            question=question,
            key="mood",
            value="7",
        )

        result = backfill_task(consumer_id=self.consumer_one.user_id)
        self.assertEqual(result["created"], 1)
