from rest_framework import status

from ..utils import Data
from ..utils.manager import General, Auth
from ..utils.BaseTest import BaseTest

from ...utils import Constants
from ...exercise.models import Exercise
from ...step.models import Step
from ...question.models import Question
from ...tag.models import Tag


class DuplicateExerciseTest(BaseTest):

    def endpoint(self):
        return "exercises/duplicate"


    def test_duplicate_exercise_success_admin(self):
        """
        Test successful exercise duplication by admin user.
        Verifies that the exercise and all nested objects are properly duplicated.
        """
        tag1 = Tag.objects.create(name="Tag 1")
        tag2 = Tag.objects.create(name="Tag 2")

        exercise_data = Data.valid_exercise_flexible_thinking()
        exercise_data["steps"] = [
            {
                **step,
                "average_duration": step.get("average_duration", 300),
                "success_title": step.get("success_title", "Well Done!")
            }
            for step in exercise_data["steps"]
        ]
        exercise_data["questions"] = [
            {
                "title": "Are you ready?",
                "attribute_key": "attr_1",
                "type": Constants.QUESTION_TYPE_BOOLEAN,
                "suggested_responses": [],
                "pre_exercise": True,
                "can_complete_exercise": True,
                "complete_on_value": "no",
                "complete_text": "Let's try again another time!"
            },
            {
                "title": "How are you feeling?",
                "attribute_key": "attr_2",
                "type": Constants.QUESTION_TYPE_SINGLE_CHOICE,
                "suggested_responses": ["Good", "Okay", "Bad"],
                "pre_exercise": False
            },
        ]

        original_exercise = General.create_exercise(data=exercise_data)
        first_step = original_exercise.steps.first()
        first_step.tags.add(tag1, tag2)


        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "Duplicated Flexible Thinking"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json


        self.assertNotEqual(response_data["id"], original_exercise.id)
        self.assertTrue(response_data["id"].startswith("exrcs_"))


        self.assertEqual(response_data["title"], "Duplicated Flexible Thinking")


        self.assertEqual(response_data["subtitle"], original_exercise.subtitle)
        self.assertEqual(response_data["description"], original_exercise.description)
        self.assertEqual(response_data["icon"], original_exercise.icon)
        self.assertEqual(response_data["icon_background_color"], original_exercise.icon_background_color)


        self.assertEqual(response_data["status"], Constants.EXERCISE_STATUS_DRAFT)


        self.assertEqual(response_data["completions_no"], 0)


        self.assertEqual(response_data["steps_no"], original_exercise.steps_no)


        duplicated_exercise = Exercise.objects.get(id=response_data["id"])


        original_steps = original_exercise.steps.all().order_by('order')
        duplicated_steps = duplicated_exercise.steps.all().order_by('order')

        self.assertEqual(original_steps.count(), duplicated_steps.count())

        for orig_step, dup_step in zip(original_steps, duplicated_steps):

            self.assertNotEqual(orig_step.id, dup_step.id)


            self.assertEqual(orig_step.title, dup_step.title)
            self.assertEqual(orig_step.description, dup_step.description)
            self.assertEqual(orig_step.instructions, dup_step.instructions)
            self.assertEqual(orig_step.completion_criteria, dup_step.completion_criteria)
            self.assertEqual(orig_step.completion_label, dup_step.completion_label)
            self.assertEqual(orig_step.completion_prompt, dup_step.completion_prompt)
            self.assertEqual(orig_step.order, dup_step.order)
            self.assertEqual(orig_step.average_duration, dup_step.average_duration)
            self.assertEqual(orig_step.success_title, dup_step.success_title)


            orig_tags = set(orig_step.tags.values_list('id', flat=True))
            dup_tags = set(dup_step.tags.values_list('id', flat=True))
            self.assertEqual(orig_tags, dup_tags)


        original_questions = original_exercise.questions.all().order_by('order')
        duplicated_questions = duplicated_exercise.questions.all().order_by('order')

        self.assertEqual(original_questions.count(), duplicated_questions.count())

        for orig_q, dup_q in zip(original_questions, duplicated_questions):

            self.assertNotEqual(orig_q.id, dup_q.id)


            self.assertEqual(orig_q.type, dup_q.type)
            self.assertEqual(orig_q.title, dup_q.title)
            self.assertEqual(orig_q.attribute_key, dup_q.attribute_key)
            self.assertEqual(orig_q.suggested_responses, dup_q.suggested_responses)
            self.assertEqual(orig_q.order, dup_q.order)
            self.assertEqual(orig_q.survey, dup_q.survey)
            self.assertEqual(orig_q.pre_exercise, dup_q.pre_exercise)
            self.assertEqual(orig_q.can_complete_exercise, dup_q.can_complete_exercise)
            self.assertEqual(orig_q.complete_on_value, dup_q.complete_on_value)
            self.assertEqual(orig_q.complete_text, dup_q.complete_text)


            self.assertIsNone(dup_q.session)


        self.assertEqual(response_data["average_duration"], original_exercise.average_duration)

    def test_duplicate_exercise_missing_exercise_field(self):
        """
        Test that duplication fails when 'exercise' field is missing.
        """
        duplicate_data = {
            "name": "New Name"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exercise", response.json)
        self.assertEqual(response.json["exercise"][0], "This field is required.")

    def test_duplicate_exercise_missing_name_field(self):
        """
        Test that duplication fails when 'name' field is missing.
        """
        original_exercise = General.create_exercise()

        duplicate_data = {
            "exercise": original_exercise.id
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.json)
        self.assertEqual(response.json["name"][0], "This field is required.")

    def test_duplicate_exercise_not_found(self):
        """
        Test that duplication fails when exercise doesn't exist.
        """
        duplicate_data = {
            "exercise": "exrcs_nonexistent",
            "name": "New Name"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("exercise", response.json)
        self.assertIn("does not exist", response.json["exercise"][0])

    def test_duplicate_exercise_consumer_forbidden(self):
        """
        Test that consumers cannot duplicate exercises (admin-only feature).
        """
        original_exercise = General.create_exercise()

        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "Duplicated by Consumer"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.consumer_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json["detail"], "Only admin accounts are able to access this")

    def test_duplicate_exercise_unauthenticated(self):
        """
        Test that unauthenticated users cannot duplicate exercises.
        """
        original_exercise = General.create_exercise()

        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "Duplicated without Auth"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=""
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_duplicate_exercise_without_questions(self):
        """
        Test duplicating an exercise that has no questions.
        """

        exercise_data = Data.valid_exercise_flexible_thinking()
        exercise_data["steps"] = [
            {
                **step,
                "average_duration": step.get("average_duration", 300),
                "success_title": step.get("success_title", "Well Done!")
            }
            for step in exercise_data["steps"]
        ]
        exercise_data["questions"] = []

        response = super()._post("/exercises", exercise_data, access_token=self.admin_one_access_token)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        original_exercise = Exercise.objects.get(id=response.json["id"])


        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "Duplicated Without Questions"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_data = response.json


        duplicated_exercise = Exercise.objects.get(id=response_data["id"])
        self.assertEqual(duplicated_exercise.questions.count(), 0)

    def test_duplicate_preserves_order(self):
        """
        Test that the order of steps and questions is preserved during duplication.
        """
        original_exercise = General.create_exercise()


        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "Order Test"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        duplicated_exercise = Exercise.objects.get(id=response.json["id"])


        original_steps_order = list(original_exercise.steps.values_list('order', flat=True).order_by('order'))
        duplicated_steps_order = list(duplicated_exercise.steps.values_list('order', flat=True).order_by('order'))
        self.assertEqual(original_steps_order, duplicated_steps_order)

 
        original_questions_order = list(original_exercise.questions.values_list('order', flat=True).order_by('order'))
        duplicated_questions_order = list(duplicated_exercise.questions.values_list('order', flat=True).order_by('order'))
        self.assertEqual(original_questions_order, duplicated_questions_order)

    def test_duplicate_creates_new_database_objects(self):
        """
        Test that duplication creates completely new database objects,
        not just references to existing ones.
        """
        original_exercise = General.create_exercise()

        original_steps_count = Step.objects.count()
        original_questions_count = Question.objects.count()
        original_exercises_count = Exercise.objects.count()


        duplicate_data = {
            "exercise": original_exercise.id,
            "name": "New Objects Test"
        }

        response = super()._post(
            f"/{self.endpoint()}",
            duplicate_data,
            access_token=self.admin_one_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


        self.assertEqual(Exercise.objects.count(), original_exercises_count + 1)
        self.assertEqual(Step.objects.count(), original_steps_count + original_exercise.steps.count())
        self.assertEqual(Question.objects.count(), original_questions_count + original_exercise.questions.count())

    def test_duplicate_exercise_different_names(self):
        """
        Test duplicating the same exercise multiple times with different names.
        """
        original_exercise = General.create_exercise()

        names = ["Copy 1", "Copy 2", "Copy 3"]
        duplicated_ids = []

        for name in names:
            duplicate_data = {
                "exercise": original_exercise.id,
                "name": name
            }

            response = super()._post(
                f"/{self.endpoint()}",
                duplicate_data,
                access_token=self.admin_one_access_token
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            response_data = response.json

            self.assertEqual(response_data["title"], name)
            duplicated_ids.append(response_data["id"])


        self.assertEqual(len(duplicated_ids), len(set(duplicated_ids)))


        for dup_id in duplicated_ids:
            self.assertNotEqual(dup_id, original_exercise.id)
