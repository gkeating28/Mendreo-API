from ..utils import Data
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_image_data(),
            ),
            CreateData(
                request_data=Data.valid_image_data(blur_hash="BLUR_HASH"),
            ),
        ]

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        # see admin entry for invalid variations
        return []

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_image_data(),
            ),
            CreateData(
                request_data=Data.valid_image_data(blur_hash="BLUR_HASH"),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(key="name", value="This field is required.")
            ),
            CreateData(
                request_data={"name": "name.jpg", "width": 100},
                response_error=ResponseError(key="height", value="This field is required.")
            ),

            CreateData(
                request_data={"name": "name.jpg", "height": 100},
                response_error=ResponseError(key="width", value="This field is required.")
            ),
            CreateData(
                request_data=Data.valid_image_data(""),
                response_error=ResponseError(key="name", value="This field may not be blank.")
            ),
            CreateData(
                request_data=Data.valid_image_data("name"),
                response_error=ResponseError(key="name", value="name is missing extension")
            ),
            CreateData(
                request_data={"name": "name.jpg", "width": -100, "height": 100},
                response_error=ResponseError(key="width", value="Ensure this value is greater than or equal to 1.")
            ),
            CreateData(
                request_data={"name": "name.jpg", "width": 100, "height": -100},
                response_error=ResponseError(key="height", value="Ensure this value is greater than or equal to 1.")
            ),
        ]

    def validate_create_response_data(self, create_data, response_json):

        self.assertIsNotNone(response_json["pre_signed_url"])
        self.assertIsNotNone(response_json["image"]["original"])
        self.assertIsNotNone(response_json["image"]["thumbnail"])
        self.assertIsNotNone(response_json["image"]["banner"])

        self.assertEqual(response_json["image"]["name"], create_data["name"])
        self.assertEqual(response_json["image"]["width"], create_data["width"])
        self.assertEqual(response_json["image"]["height"], create_data["height"])

        self.assertIsNotNone(response_json["image"]["token"])
        self.assertFalse(response_json["image"]["uploaded"])

    def endpoint(self):
        return "images"


del BaseCreateTest
