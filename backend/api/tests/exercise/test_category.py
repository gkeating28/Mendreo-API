from rest_framework import status

from ..utils import Data
from ..utils.BaseTest import BaseTest
from ..utils.manager import General
from ...exercise.models import Exercise


class ExerciseCategoryTests(BaseTest):
    def endpoint(self):
        return "exercises"

    def test_create_includes_category(self):
        data = Data.valid_exercise_flexible_thinking()
        data["category"] = "Mindfulness"

        response = self._create(data, self.admin_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json)
        self.assertEqual(response.json["category"], "Mindfulness")

        exercise = Exercise.objects.get(id=response.json["id"])
        self.assertEqual(exercise.category, "Mindfulness")

    def test_list_filter_by_category(self):
        mindfulness = Data.valid_exercise_flexible_thinking()
        mindfulness["title"] = "Breathing"
        mindfulness["category"] = "Mindfulness"
        General.create_exercise(mindfulness)

        thinking = Data.valid_exercise_flexible_thinking()
        thinking["title"] = "Reframe"
        thinking["category"] = "Thinking"
        General.create_exercise(thinking)

        listed = self._list(
            self.consumer_one_access_token,
            {"category": "Mindfulness", "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        titles = [row["title"] for row in listed.json]
        categories = {row["category"] for row in listed.json}
        self.assertIn("Breathing", titles)
        self.assertNotIn("Reframe", titles)
        self.assertEqual(categories, {"Mindfulness"})

    def test_category_filter_is_case_insensitive(self):
        data = Data.valid_exercise_flexible_thinking()
        data["title"] = "Grounding"
        data["category"] = "Calm"
        General.create_exercise(data)

        listed = self._list(
            self.consumer_one_access_token,
            {"category": "calm", "paginated": "false"},
        )
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        self.assertTrue(any(row["title"] == "Grounding" for row in listed.json))

    def test_edit_category(self):
        exercise = General.create_exercise()
        patched = self._update(
            exercise,
            {"category": "Sleep"},
            self.admin_one_access_token,
        )
        self.assertEqual(patched.status_code, status.HTTP_200_OK, patched.json)
        self.assertEqual(patched.json["category"], "Sleep")
        exercise.refresh_from_db()
        self.assertEqual(exercise.category, "Sleep")
