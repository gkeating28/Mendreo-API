from rest_framework import status

from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData
from ..utils.BaseTest import ResponseError

from ...utils import Constants


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        return []

    def get_invalid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        data = Data.valid_exercise_flexible_thinking()

        return [
            CreateData(
                request_data=data,
                response_error=ResponseError(
                    key="detail",
                    value="You do not have permission to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        data = Data.valid_exercise_flexible_thinking()

        data_with_average_duration = {
            **data,
            "steps": [
                {
                    **step,
                    "average_duration": step.get("average_duration", 300),
                    "success_title": step.get("success_title", "Well Done!")
                }
                for step in data["steps"]
            ]
        }

        return [
            CreateData(
                request_data=data_with_average_duration,
            ),
            CreateData(
                request_data={
                    **data_with_average_duration,
                    "questions": []
                }
            ),
            CreateData(
                request_data={
                    **data_with_average_duration,
                    "questions": [
                        {
                            "title": "Are you ready?",
                            "attribute_key": "attr_1",
                            "type": Constants.QUESTION_TYPE_BOOLEAN,
                            "suggested_responses": [],
                            "pre_exercise": True,
                            "can_complete_exercise": True,
                            "complete_on_value": "no",
                            "complete_text": "Lets try again another time!"
                        },
                        {
                            "title": "You sure?",
                            "attribute_key": "attr_2",
                            "type": Constants.QUESTION_TYPE_BOOLEAN,
                            "suggested_responses": [],
                            "pre_exercise": True,
                            "can_complete_exercise": True,
                            "complete_on_value": "false",
                            "complete_text": "Lets try again another time!"
                        },
                    ]
                },
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        data = Data.valid_exercise_flexible_thinking()

        valid_question_data = {
            "title": "Are you ready?",
            "attribute_key": "attr_1",
            "type": Constants.QUESTION_TYPE_BOOLEAN,
            "suggested_responses": [],
            "pre_exercise": True,
            "can_complete_exercise": True,
            "complete_on_value": "no",
            "complete_text": "Lets try again another time!"
        }

        return [
            CreateData(
                request_data={
                    **data,
                    "title": ""
                },
                response_error=ResponseError(
                    key="title",
                    value="This field may not be blank."
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "steps": []
                },
                response_error=ResponseError(
                    key="steps",
                    value="{'non_field_errors': ['This list may not be empty.']}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "complete_on_value": "maybe"
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'complete_on_value': [\"must be one of: ['true', 'false', 'yes', 'no']\"]}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "pre_exercise": False,
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'pre_exercise': [\"Must be true if 'can_complete_exercise' is True\"]}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "type": Constants.QUESTION_TYPE_TEXT,
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'can_complete_exercise': ['This field is cannot be true for type text']}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "complete_on_value": None
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'complete_on_value': [\"This field is required when 'can_complete_exercise' is True\"]}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "can_complete_exercise": False
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'can_complete_exercise': [\"This field must be True when 'complete_on_value' is set\"]}"
                )
            ),
            CreateData(
                request_data={
                    **data,
                    "questions": [
                        {
                            **valid_question_data,
                            "complete_text": None
                        },
                    ]
                },
                response_error=ResponseError(
                    key="questions",
                    value="{'complete_text': [\"This field is required when 'can_complete_exercise' is True\"]}"
                )
            ),
        ]

    def validate_create_response_data(self, create_data, response_json):
        keys = [
            "title",
            "subtitle",
            "description",
            "status",
            "icon",
            "icon_background_color"
        ]

        self.assertTrue(response_json["id"].startswith("exrcs_"))
        for key in keys:
            self.assertEqual(create_data[key].strip(), response_json[key].strip())

        self.assertEqual(response_json["steps_no"], len(create_data["steps"]))
        self.assertEqual(len(response_json["questions"]), len(create_data["questions"]))

        self.assertIn("order", response_json)
        self.assertIsInstance(response_json["order"], int)
        self.assertGreaterEqual(response_json["order"], 0)

        total_duration = 0

        for i, step_data in enumerate(create_data["steps"]):
            step_keys = [
                "title",
                "description",
                "instructions",
                "completion_criteria",
                "completion_label",
                "completion_prompt",
                "average_duration",
                "success_title"
            ]

            for step_key in step_keys:
                self.assertEqual(
                    str(step_data[step_key]).strip(),
                    str(response_json["steps"][i][step_key]).strip()
                )

            total_duration += step_data["average_duration"]

        self.assertEqual(response_json["average_duration"], total_duration)

        for i, question_data in enumerate(create_data["questions"]):
            question_response_data = response_json["questions"][i]

            self.assertEqual(i, question_response_data["order"])
            self.assertEqual(question_data["type"], question_response_data["type"])
            self.assertEqual(question_data["title"], question_response_data["title"])
            self.assertEqual(question_data["attribute_key"], question_response_data["attribute_key"])
            self.assertEqual(question_data["pre_exercise"], question_response_data["pre_exercise"])
            self.assertEqual(question_data["suggested_responses"], question_response_data["suggested_responses"])

    def endpoint(self):
        return "exercises"


del BaseCreateTest
