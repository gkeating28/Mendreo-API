from ..utils import Data
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        # consumer not allowed to upload file
        return []

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_file_data(),
                response_error=ResponseError(
                    key="detail",
                    value="Only admin accounts are able to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_file_data(),
            ),
            CreateData(
                request_data=Data.valid_file_data("sample.pdf"),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(key="name", value="This field is required.")
            ),
            CreateData(
                request_data=Data.valid_file_data(""),
                response_error=ResponseError(key="name", value="This field may not be blank.")
            ),
            CreateData(
                request_data=Data.valid_file_data("name"),
                response_error=ResponseError(key="name", value="name is missing extension")
            ),
            CreateData(
                request_data=Data.valid_file_data(duration=-1),
                response_error=ResponseError(key="duration", value="Ensure this value is greater than or equal to 0.")
            ),
        ]

    def validate_create_response_data(self, create_data, response_json):
        self.assertIsNotNone(response_json["pre_signed_url"])
        self.assertIsNotNone(response_json["content_type"])
        self.assertIsNotNone(response_json["file"]["url"])

        self.assertEqual(response_json["file"]["name"], create_data["name"])
        self.assertEqual(response_json["file"]["size"], create_data["size"])
        self.assertEqual(response_json["file"]["duration"], create_data["duration"])

        self.assertIsNotNone(response_json["file"]["token"])
        self.assertFalse(response_json["file"]["uploaded"])

    def endpoint(self):
        return "files"


del BaseCreateTest
