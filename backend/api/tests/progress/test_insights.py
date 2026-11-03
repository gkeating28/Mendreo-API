import inspect
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from ...knowledge.models import KnowledgeEntry, KnowledgeField
from ...progress import insights as insights_module
from ...progress.insights import (
    RESULT_DISABLED,
    RESULT_EMPTY,
    RESULT_FAILED,
    RESULT_GENERATED,
    RESULT_NO_SOURCES,
    RESULT_UNCHANGED,
    generate_insights_for_consumer,
    next_hand,
)
from ...progress.models import UserInsight, UserInsightCursor
from ...session.models import Session
from ...setting.models import Setting
from ...utils import Constants
from ..TestCase import TestCase
from ..utils.manager import Auth, General


class InsightTests(TestCase):
    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.exercise = General.create_exercise()
        self.walk = KnowledgeField.objects.create(
            key="walk_habit",
            label="Walk",
            category="Wellbeing",
            active=True,
        )
        self.meds = KnowledgeField.objects.create(
            key="medication_name",
            label="Medication",
            category="Health",
            sensitive=True,
            active=True,
        )

    def _entry(self, field, value, consumer=None):
        return KnowledgeEntry.objects.create(
            consumer=consumer or self.consumer,
            field=field,
            value=value,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
        )

    def _run(self, line, bullets=None, *, when=None, risk="low", consumer=None, summary=True):
        session = Session.objects.create(
            consumer=consumer or self.consumer,
            exercise=self.exercise,
            completed=True,
            completed_at=when or timezone.now(),
            risk_level=risk,
            run_summary=(
                {"line": line, "bullets": bullets or []}
                if summary
                else None
            ),
        )
        return session

    def _set(self, key, value):
        row = Setting.objects.get(key=key)
        row.value = str(value)
        row.save()

    def test_unchanged_fingerprint_skips_the_model(self):
        self._entry(self.walk, "likes walking")
        calls = []

        def ask(prompt, schema, temperature=0.3):
            calls.append((prompt, temperature))
            return {
                "insights": [
                    {
                        "text": "one two three four five six",
                        "topic_key": "walks",
                        "source_run_id": "",
                    }
                ]
            }

        self._set(Constants.SETTING_KEY_INSIGHTS_MAX_LENGTH, 3)
        with patch("api.utils.AI.AI.ask", side_effect=ask):
            first = generate_insights_for_consumer(self.consumer)
            second = generate_insights_for_consumer(self.consumer)

        self.assertEqual(first, RESULT_GENERATED)
        self.assertEqual(second, RESULT_UNCHANGED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 0.4)
        stored = UserInsight.objects.get(consumer=self.consumer)
        self.assertEqual(stored.text, "one two three")
        self.assertIsNotNone(UserInsightCursor.objects.get(consumer=self.consumer).source_fingerprint)

    def test_no_sources_and_disabled_skip_the_model(self):
        with patch("api.utils.AI.AI.ask") as ask:
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_NO_SOURCES)
            self._entry(self.walk, "likes walking")
            self._set(Constants.SETTING_KEY_INSIGHTS_ENABLED, "false")
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_DISABLED)
        ask.assert_not_called()

    def test_blocked_run_is_left_out_and_an_earlier_run_is_used(self):
        now = timezone.now()
        earlier = self._run(
            "EARLIER_RUN_LINE",
            ["kept bullet"],
            when=now - timedelta(days=2),
        )
        self._run(
            "HIGH_RISK_SECRET",
            ["do not send"],
            when=now - timedelta(days=1),
            risk=Constants.RISK_LEVEL_HIGH,
        )
        captured = {}

        def ask(prompt, schema, temperature=0.3):
            captured["prompt"] = prompt
            return {
                "insights": [
                    {
                        "text": "Stay with the earlier run",
                        "topic_key": "earlier",
                        "source_run_id": earlier.id,
                    }
                ]
            }

        with patch("api.utils.AI.AI.ask", side_effect=ask):
            result = generate_insights_for_consumer(self.consumer)

        self.assertEqual(result, RESULT_GENERATED)
        self.assertIn("EARLIER_RUN_LINE", captured["prompt"])
        self.assertIn(str(earlier.id), captured["prompt"])
        self.assertNotIn("HIGH_RISK_SECRET", captured["prompt"])
        stored = UserInsight.objects.get(consumer=self.consumer)
        self.assertEqual(stored.source_run_id, earlier.id)

    def test_sensitive_value_is_left_out_and_dropped(self):
        self._entry(self.walk, "likes walking")
        self._entry(self.meds, "SertralineSecret")
        dose = KnowledgeField.objects.create(
            key="dose_count", label="Dose", category="Health", sensitive=True, active=True
        )
        confirm = KnowledgeField.objects.create(
            key="confirm_word", label="Confirm", category="Health", sensitive=True, active=True
        )
        feeling = KnowledgeField.objects.create(
            key="feeling_word", label="Feeling", category="Health", sensitive=True, active=True
        )
        self._entry(dose, "7")
        self._entry(confirm, "yes")
        self._entry(feeling, "panic")
        captured = {}

        def ask(prompt, schema, temperature=0.3):
            captured["prompt"] = prompt
            return {
                "insights": [
                    {
                        "text": "I said yes about 7 days yesterday",
                        "topic_key": "short",
                        "source_run_id": "",
                    },
                    {
                        "text": "I feel panicked but okay",
                        "topic_key": "panic-stem",
                        "source_run_id": "",
                    },
                    {
                        "text": "I feel panic today",
                        "topic_key": "panic-word",
                        "source_run_id": "",
                    },
                    {
                        "text": "You could mention SertralineSecret today",
                        "topic_key": "medicine",
                        "source_run_id": "",
                    },
                    {
                        "text": "You could talk about the walk",
                        "topic_key": "walks",
                        "source_run_id": "",
                    },
                ]
            }

        with patch("api.utils.AI.AI.ask", side_effect=ask):
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_GENERATED)

        self.assertIn("likes walking", captured["prompt"])
        self.assertNotIn("SertralineSecret", captured["prompt"])
        self.assertNotIn("panic", captured["prompt"])
        stored = list(
            UserInsight.objects.filter(consumer=self.consumer).order_by("generated_at", "id")
        )
        self.assertEqual(
            [item.topic_key for item in stored],
            ["short", "panic-stem", "walks"],
        )

    def test_duplicates_are_dropped_and_a_foreign_run_is_cleared(self):
        self._entry(self.walk, "likes walking")
        UserInsight.objects.create(
            consumer=self.consumer,
            text="The deadline is already in the pool",
            topic_key="deadline",
            generated_at=timezone.now() - timedelta(days=1),
        )
        other = Auth.create_consumer()
        foreign = self._run("FOREIGN_RUN", consumer=other)

        def ask(prompt, schema, temperature=0.3):
            return {
                "insights": [
                    {"text": "A different deadline line", "topic_key": "Deadline", "source_run_id": ""},
                    {
                        "text": "Ask about music",
                        "topic_key": "music",
                        "source_run_id": foreign.id,
                    },
                    {
                        "text": "Ask about music again",
                        "topic_key": "Music",
                        "source_run_id": "ssn_missing",
                    },
                    {
                        "text": "ask   about music",
                        "topic_key": "playlist",
                        "source_run_id": "",
                    },
                ]
            }

        with patch("api.utils.AI.AI.ask", side_effect=ask):
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_GENERATED)

        rows = list(
            UserInsight.objects.filter(consumer=self.consumer, retired_at__isnull=True).order_by(
                "generated_at", "id"
            )
        )
        self.assertEqual([row.topic_key for row in rows], ["deadline", "music"])
        self.assertIsNone(rows[1].source_run_id)
        self.assertNotIn(foreign.id, [row.source_run_id for row in rows])

    def test_cap_retires_the_oldest(self):
        self._entry(self.walk, "likes walking")
        self._set(Constants.SETTING_KEY_INSIGHTS_POOL_CAP, 2)
        older = UserInsight.objects.create(
            consumer=self.consumer,
            text="Oldest starter",
            topic_key="oldest",
            generated_at=timezone.now() - timedelta(days=3),
        )
        middle = UserInsight.objects.create(
            consumer=self.consumer,
            text="Middle starter",
            topic_key="middle",
            generated_at=timezone.now() - timedelta(days=2),
        )

        def ask(prompt, schema, temperature=0.3):
            return {
                "insights": [
                    {"text": "Newest one", "topic_key": "new-one", "source_run_id": ""},
                    {"text": "Newest two", "topic_key": "new-two", "source_run_id": ""},
                ]
            }

        with patch("api.utils.AI.AI.ask", side_effect=ask):
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_GENERATED)

        older.refresh_from_db()
        middle.refresh_from_db()
        self.assertIsNotNone(older.retired_at)
        self.assertIsNotNone(middle.retired_at)
        active = list(
            UserInsight.objects.filter(consumer=self.consumer, retired_at__isnull=True).order_by(
                "topic_key"
            )
        )
        self.assertEqual([item.topic_key for item in active], ["new-one", "new-two"])

    def test_model_failure_and_empty_result_keep_the_pool_and_cursor(self):
        self._entry(self.walk, "likes walking")
        kept = UserInsight.objects.create(
            consumer=self.consumer,
            text="Keep this starter",
            topic_key="kept",
            generated_at=timezone.now() - timedelta(days=1),
        )
        cursor = UserInsightCursor.objects.create(
            consumer=self.consumer,
            source_fingerprint="previous-fingerprint",
            checked_at=timezone.now() - timedelta(days=1),
        )

        with patch("api.utils.AI.AI.ask", side_effect=RuntimeError("down")):
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_FAILED)
        kept.refresh_from_db()
        cursor.refresh_from_db()
        self.assertIsNone(kept.retired_at)
        self.assertEqual(cursor.source_fingerprint, "previous-fingerprint")
        self.assertEqual(UserInsight.objects.filter(consumer=self.consumer).count(), 1)

        with patch("api.utils.AI.AI.ask", return_value={"insights": []}):
            self.assertEqual(generate_insights_for_consumer(self.consumer), RESULT_EMPTY)
        cursor.refresh_from_db()
        self.assertEqual(cursor.source_fingerprint, "previous-fingerprint")
        self.assertEqual(UserInsight.objects.filter(consumer=self.consumer).count(), 1)

    def test_next_hand_stays_put_below_the_minimum_and_rotates_when_it_can(self):
        base = timezone.now() - timedelta(days=10)
        small = [
            self._insight(f"small-{index}", base + timedelta(hours=index))
            for index in range(3)
        ]
        first = next_hand(self.consumer, force_rotate=True)
        self.assertFalse(first.can_refresh)
        self.assertEqual([item.id for item in first.items], [item.id for item in small])
        again = next_hand(self.consumer, force_rotate=True)
        self.assertEqual([item.id for item in again.items], [item.id for item in small])
        self.assertEqual(
            set(
                UserInsight.objects.filter(id__in=[item.id for item in small]).values_list(
                    "show_count", flat=True
                )
            ),
            {1},
        )

        UserInsight.objects.filter(id__in=[item.id for item in small]).update(
            retired_at=timezone.now(),
            in_hand=False,
        )
        other = self._other()
        mine = [
            self._insight(f"pool-{index}", base + timedelta(hours=index))
            for index in range(8)
        ]
        opened = next_hand(self.consumer)
        self.assertTrue(opened.can_refresh)
        self.assertEqual([item.id for item in opened.items], [item.id for item in mine[:4]])
        reopened = next_hand(self.consumer)
        self.assertEqual([item.id for item in reopened.items], [item.id for item in mine[:4]])
        self.assertEqual(UserInsight.objects.get(id=mine[0].id).show_count, 1)

        rotated = next_hand(self.consumer, force_rotate=True)
        self.assertEqual([item.id for item in rotated.items], [item.id for item in mine[4:]])
        self.assertEqual(UserInsight.objects.get(id=mine[0].id).in_hand, False)
        self.assertEqual(UserInsight.objects.get(id=mine[4].id).in_hand, True)

        theirs = next_hand(other)
        self.assertEqual(list(theirs.items), [])
        self.assertTrue(
            all(item.consumer_id == self.consumer.pk for item in UserInsight.objects.filter(in_hand=True))
        )

    def test_new_insights_refresh_a_hand_once_and_a_short_hand_is_topped_up(self):
        source = inspect.getsource(insights_module.next_hand)
        self.assertIn("transaction.atomic", source)
        self.assertIn("select_for_update", source)

        base = timezone.now() - timedelta(days=5)
        held = [self._insight(f"held-{index}", base + timedelta(hours=index)) for index in range(4)]
        waiting = self._insight("waiting", base + timedelta(hours=4))
        opened = next_hand(self.consumer)
        self.assertEqual([item.id for item in opened.items], [item.id for item in held])

        nightly = [
            self._insight("nightly-0", timezone.now() + timedelta(minutes=1)),
            self._insight("nightly-1", timezone.now() + timedelta(minutes=2)),
        ]
        refreshed = next_hand(self.consumer)
        refreshed_ids = [item.id for item in refreshed.items]
        self.assertEqual(refreshed_ids, [waiting.id, nightly[0].id, nightly[1].id, held[0].id])
        again = next_hand(self.consumer)
        self.assertEqual([item.id for item in again.items], refreshed_ids)
        self.assertEqual(UserInsight.objects.get(id=nightly[0].id).show_count, 1)

        UserInsight.objects.filter(consumer=self.consumer).update(retired_at=timezone.now(), in_hand=False)
        pool = [self._insight(f"top-{index}", base + timedelta(hours=index)) for index in range(6)]
        first = next_hand(self.consumer)
        self.assertEqual([item.id for item in first.items], [item.id for item in pool[:4]])
        UserInsight.objects.filter(id__in=[pool[0].id, pool[1].id]).update(
            retired_at=timezone.now(),
            in_hand=False,
        )
        topped = next_hand(self.consumer)
        self.assertEqual(
            [item.id for item in topped.items],
            [pool[4].id, pool[5].id, pool[2].id, pool[3].id],
        )
        topped_again = next_hand(self.consumer)
        self.assertEqual([item.id for item in topped_again.items], [item.id for item in topped.items])

        self._set(Constants.SETTING_KEY_INSIGHTS_MIN_POOL_BEFORE_SHUFFLE, 10)
        UserInsight.objects.filter(consumer=self.consumer).update(retired_at=timezone.now(), in_hand=False)
        small = [self._insight(f"stay-{index}", base + timedelta(hours=index)) for index in range(4)]
        stayed = next_hand(self.consumer)
        self.assertEqual([item.id for item in stayed.items], [item.id for item in small])
        newer = self._insight("newer", timezone.now() + timedelta(hours=1))
        held_open = next_hand(self.consumer)
        self.assertEqual([item.id for item in held_open.items], [item.id for item in small])
        self.assertNotIn(newer.id, [item.id for item in held_open.items])
        forced = next_hand(self.consumer, force_rotate=True)
        self.assertEqual([item.id for item in forced.items], [item.id for item in small])

    def _other(self):
        if not hasattr(self, "other_consumer"):
            self.other_consumer = Auth.create_consumer()
        return self.other_consumer

    def _insight(self, topic, generated_at, consumer=None):
        return UserInsight.objects.create(
            consumer=consumer or self.consumer,
            text=f"Starter about {topic}",
            topic_key=topic,
            generated_at=generated_at,
        )
