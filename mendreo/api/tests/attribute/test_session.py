from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ...utils import Constants

from rest_framework import status


class SessionTest(BaseCreateTest):

    def setUp(self):
        super().setUp()
        exercise_data = Data.valid_exercise_flexible_thinking()

        exercise_data["questions"] = [
            {
                **Data.valid_question_data(type_="text", attribute_key="attr_1"),
                "pre_exercise": True,
            },
            {
                "title": "Are you ready?",
                "attribute_key": "attr_2",
                "type": Constants.QUESTION_TYPE_BOOLEAN,
                "suggested_responses": [],
                "pre_exercise": True,
                "can_complete_exercise": True,
                "complete_on_value": "no",
                "complete_text": "That's too bad, lets try tomorrow!"
            },
            {
                "title": "Are you not sure?",
                "attribute_key": "attr_3",
                "type": Constants.QUESTION_TYPE_BOOLEAN,
                "suggested_responses": [],
                "pre_exercise": True,
                "can_complete_exercise": True,
                "complete_on_value": "yes",
                "complete_text": "Another time so!"
            }
        ]

        self.exercise = General.create_exercise(data=exercise_data)

        self.session = General.create_session(self.consumer_one, exercise=self.exercise)

        self.first_question = self.session.questions.get(attribute_key="attr_1")
        self.second_question = self.session.questions.get(attribute_key="attr_2")
        self.third_question = self.session.questions.get(attribute_key="attr_3")

    def test_session_marked_completed_for_blocking_answer(self):
        request_data = {
            "question": self.first_question.id,
            "value": "yes",
        }

        response = self._create(request_data, self.consumer_one_access_token)

        self.session.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(self.session.completed)

        request_data = {
            "question": self.second_question.id,
            "value": "yes",
        }

        response = self._create(request_data, self.consumer_one_access_token)

        self.session.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(self.session.completed)

        request_data = {
            "question": self.third_question.id,
            "value": "yes",
        }

        response = self._create(request_data, self.consumer_one_access_token)

        self.session.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(self.session.completed)

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:

        return [
            CreateData(
                request_data={
                    "question": self.first_question.id,
                    "value": "Text"
                },
            ),
            CreateData(
                request_data={
                    "question": self.second_question.id,
                    "value": "yes"
                },
            ),
            CreateData(
                request_data={
                    "question": self.third_question.id,
                    "value": "no"
                },
            ),
        ]

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:

        return []

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return []

    def get_invalid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return []

    def endpoint(self):
        return "attributes"


del BaseCreateTest
