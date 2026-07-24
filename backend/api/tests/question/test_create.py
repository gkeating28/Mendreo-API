from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        # consumer not allowed to create questions
        return []

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(
                    key="detail",
                    value="You do not have permission to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_question_data(),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="text",
                    attribute_key="text",
                    suggested_responses=["Anxiety", "Depression"]
                ),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="number",
                    attribute_key="number",
                ),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="number",
                    attribute_key="number_opt",
                    suggested_responses=[1, 2]
                ),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="boolean",
                    attribute_key="boolean",
                ),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="single_choice",
                    attribute_key="single_choice",
                    suggested_responses=["Option 1", "Option 2"]
                ),
            ),
            CreateData(
                request_data=Data.valid_question_data(
                    type_="multiple_choice",
                    attribute_key="multiple_choice",
                    suggested_responses=["Option 1", "Option 2", "Option 3"]
                ),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(key="title", value="This field is required.")
            ),
            CreateData(
                request_data=Data.valid_question_data(title=""),
                response_error=ResponseError(key="title", value="This field may not be blank.")
            ),
            CreateData(
                request_data=Data.valid_question_data(type_="invalid"),
                response_error=ResponseError(key="type", value='"invalid" is not a valid choice.')
            ),
            CreateData(
                request_data=Data.valid_question_data(type_="boolean", suggested_responses=["in", "valid"]),
                response_error=ResponseError(key="type", value="'boolean' can not have 'suggested_responses'")
            ),
            CreateData(
                request_data=Data.valid_question_data(type_="single_choice", suggested_responses=[]),
                response_error=ResponseError(key="type", value="'single_choice' must have at least 2 'suggested_responses'")
            ),
            CreateData(
                request_data=Data.valid_question_data(type_="multiple_choice", suggested_responses=["Option 1"]),
                response_error=ResponseError(key="type", value="'multiple_choice' must have at least 2 'suggested_responses'")
            ),
        ]

    def endpoint(self):
        return "questions"


del BaseCreateTest
