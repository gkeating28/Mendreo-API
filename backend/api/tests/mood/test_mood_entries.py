from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from ..utils.BaseTest import BaseTest
from ..utils.manager import Auth
from ..TestCase import TestCase
from ...mood.models import MoodEntry
from ...utils import Constants


class MoodEntryApiTests(BaseTest):
    def endpoint(self):
        return "mood-entries"

    def _create_entry(self, consumer=None, mood_score=3, note="Feeling alright", days_ago=0):
        consumer = consumer or self.consumer_one
        entry = MoodEntry.objects.create(
            consumer=consumer,
            mood_score=mood_score,
            note=note,
        )
        if days_ago:
            MoodEntry.objects.filter(id=entry.id).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )
            entry.refresh_from_db()
        return entry

    def test_consumer_create_list_and_detail(self):
        create = TestCase._post(
            "/mood-entries",
            {"mood_score": 5, "note": "Great day"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.json)
        self.assertEqual(create.json["mood_score"], 5)
        self.assertEqual(create.json["mood_label"], "Great")
        self.assertEqual(create.json["note"], "Great day")
        self.assertEqual(create.json["consumer"], self.consumer_one.user_id)
        self.assertTrue(create.json["id"].startswith("mood_"))
        self.assertIn("created_at", create.json)

        # Multiple recordings per day are allowed.
        second = TestCase._post(
            "/mood-entries",
            {"mood_score": 2, "note": "Dip later"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.json)

        listed = TestCase._get(
            "/mood-entries",
            access_token=self.consumer_one_access_token,
            query_params_dict={"paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(len(listed.json), 2)

        detail = TestCase._get(
            f"/mood-entries/{create.json['id']}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.json)
        self.assertEqual(detail.json["mood_label"], "Great")

    def test_consumer_cannot_see_other_consumer_entries(self):
        other = Auth.create_consumer()
        entry = self._create_entry(consumer=other, mood_score=4, note="private")

        listed = TestCase._get(
            "/mood-entries",
            access_token=self.consumer_one_access_token,
            query_params_dict={"paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(listed.json, [])

        detail = TestCase._get(
            f"/mood-entries/{entry.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)

    def test_consumer_edit_and_delete(self):
        entry = self._create_entry(mood_score=1, note="Low")

        patched = TestCase._patch(
            f"/mood-entries/{entry.id}",
            {"mood_score": 4, "note": "Better now"},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK, patched.json)
        self.assertEqual(patched.json["mood_score"], 4)
        self.assertEqual(patched.json["mood_label"], "Good")
        self.assertEqual(patched.json["note"], "Better now")

        deleted = TestCase._delete(
            f"/mood-entries/{entry.id}",
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(deleted.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(MoodEntry.objects.filter(id=entry.id).exists())
        self.assertTrue(MoodEntry.all_objects.filter(id=entry.id).exists())

    def test_invalid_mood_score_rejected(self):
        for score in (0, 6, -1):
            response = TestCase._post(
                "/mood-entries",
                {"mood_score": score, "note": "nope"},
                access_token=self.consumer_one_access_token,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json)

    def test_note_optional(self):
        response = TestCase._post(
            "/mood-entries",
            {"mood_score": Constants.MOOD_SCORE_OKAY},
            access_token=self.consumer_one_access_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.assertEqual(response.json["note"], "")

    def test_admin_can_list_filter_and_create_for_consumer(self):
        self._create_entry(mood_score=1, note="today")
        self._create_entry(mood_score=5, note="yesterday", days_ago=1)

        listed = TestCase._get(
            "/mood-entries",
            access_token=self.admin_one_access_token,
            query_params_dict={
                "consumer_id": self.consumer_one.user_id,
                "paginated": "false",
            },
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertEqual(len(listed.json), 2)

        filtered = TestCase._get(
            "/mood-entries",
            access_token=self.admin_one_access_token,
            query_params_dict={
                "consumer_id": self.consumer_one.user_id,
                "mood_score": 5,
                "paginated": "false",
            },
        )
        self.assertEqual(filtered.status_code, status.HTTP_200_OK, filtered.json)
        self.assertEqual(len(filtered.json), 1)
        self.assertEqual(filtered.json[0]["mood_label"], "Great")

        created = TestCase._post(
            "/mood-entries",
            {
                "consumer": self.consumer_one.user_id,
                "mood_score": 3,
                "note": "Admin logged check-in",
            },
            access_token=self.admin_one_access_token,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.json)
        self.assertEqual(created.json["consumer"], self.consumer_one.user_id)

    def test_unauthenticated_rejected(self):
        response = TestCase._post("/mood-entries", {"mood_score": 3})
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
