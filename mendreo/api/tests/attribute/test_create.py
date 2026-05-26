from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        text_question = General.create_question(Data.valid_question_data(type_="text", attribute_key="text"))
        date_question = General.create_question(Data.valid_question_data(type_="date", attribute_key="data"))
        number_question = General.create_question(Data.valid_question_data(type_="number", attribute_key="number"))
        boolean_question = General.create_question(Data.valid_question_data(type_="boolean", attribute_key="boolean"))
        single_choice_question = General.create_question(
            data=Data.valid_question_data(
                type_="single_choice",
                attribute_key="single_choice",
                suggested_responses=["Choice 1", "Choice 2"]
            )
        )
        multiple_choice_question = General.create_question(
            data=Data.valid_question_data(
                type_="multiple_choice",
                attribute_key="multiple_choice",
                suggested_responses=["Choice 1", "Choice 2", "Choice 3"]
            )
        )

        return [
            CreateData(
                request_data={
                    "question": text_question.id,
                    "value": "Text"
                },
            ),
            CreateData(
                request_data={
                    "question": date_question.id,
                    "value": "2000-01-01"
                },
            ),
            CreateData(
                request_data={
                    "question": number_question.id,
                    "value": "1234"
                },
            ),
            CreateData(
                request_data={
                    "question": boolean_question.id,
                    "value": "true"
                },
            ),
            CreateData(
                request_data={
                    "question": single_choice_question.id,
                    "value": "Choice 1"
                },
            ),
            CreateData(
                request_data={
                    "question": multiple_choice_question.id,
                    "value": "Choice 1,Choice 2"
                },
            ),
        ]

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        text_question = General.create_question(Data.valid_question_data(type_="text", attribute_key="text"))
        date_question = General.create_question(Data.valid_question_data(type_="date", attribute_key="data"))
        number_question = General.create_question(Data.valid_question_data(type_="number", attribute_key="number"))
        boolean_question = General.create_question(Data.valid_question_data(type_="boolean", attribute_key="boolean"))
        single_choice_question = General.create_question(
            data=Data.valid_question_data(
                type_="single_choice",
                attribute_key="single_choice",
                suggested_responses=["Choice 1", "Choice 2"]
            )
        )
        multiple_choice_question = General.create_question(
            data=Data.valid_question_data(
                type_="multiple_choice",
                attribute_key="multiple_choice",
                suggested_responses=["Choice 1", "Choice 2", "Choice 3"]
            )
        )

        return [
            CreateData(
                request_data={
                    "question": text_question.id,
                },
                response_error=ResponseError(
                    key="value",
                    value="This field is required.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": text_question.id,
                    "value": ""
                },
                response_error=ResponseError(
                    key="value",
                    value="This field may not be blank.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": text_question.id,
                    "value": None
                },
                response_error=ResponseError(
                    key="value",
                    value="This field may not be null.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": date_question.id,
                    "value": "Tuesday"
                },
                response_error=ResponseError(
                    key="value",
                    value="'Tuesday' is not a valid data in format 'YYYY-MM-DD",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": number_question.id,
                    "value": "Forty Four"
                },
                response_error=ResponseError(
                    key="value",
                    value="'Forty Four' is not a valid number",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": boolean_question.id,
                    "value": "maybe?"
                },
                response_error=ResponseError(
                    key="value",
                    value="must be one of: ['true', 'false', 'yes', 'no']",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": single_choice_question.id,
                    "value": "Invalid choice"
                },
                response_error=ResponseError(
                    key="value",
                    value="'Invalid choice' is not a valid option",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "question": multiple_choice_question.id,
                    "value": "Choice 1,random"
                },
                response_error=ResponseError(
                    key="value",
                    value="'random' is not a valid option",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return []

    def get_invalid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return []

    def endpoint(self):
        return "attributes"
    
    def expect_status(self, response, expected_status):
        self.assertEqual(
            response.status_code,
            expected_status,
            f"Expected status {expected_status} but got {response.status_code}. Response data: {getattr(response, 'data', response.content)}"
        )


del BaseCreateTest
