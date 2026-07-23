from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        # consumer not allowed to create agents
        return []

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(
                    key="detail",
                    value="Only admin accounts are able to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        post = General.create_post()
        file = General.create_file()
        tag = General.create_tag()
        return [
            CreateData(
                request_data=Data.valid_asset_data(),
            ),
            CreateData(
                request_data=Data.valid_asset_data(post=post),
            ),
            CreateData(
                request_data=Data.valid_asset_data(file=file),
            ),
            CreateData(
                request_data=Data.valid_asset_data(tag=tag),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        post = General.create_post()
        file = General.create_file()
        image = General.create_image()
        return [
            CreateData(
                request_data={"tags": []},
                response_error=ResponseError(key="context", value="This field is required.")
            ),
            CreateData(
                request_data={"context": "Context"},
                response_error=ResponseError(key="asset", value="Must specify one of post, file or image")
            ),
            CreateData(
                request_data={"tags": [], "context": "Context"},
                response_error=ResponseError(key="asset", value="Must specify one of post, file or image")
            ),
            CreateData(
                request_data={
                    "tags": [],
                    "post": post.id,
                    "file": file.id,
                    "context": "Context"
                },
                response_error=ResponseError(key="asset", value="Can only specify one of post, file or image")
            ),
            CreateData(
                request_data={
                    "tags": [],
                    "post": post.id,
                    "image": image.id,
                    "context": "Context"
                },
                response_error=ResponseError(key="asset", value="Can only specify one of post, file or image")
            ),
            CreateData(
                request_data={
                    "tags": [],
                    "file": file.id,
                    "image": image.id,
                    "context": "Context"
                },
                response_error=ResponseError(key="asset", value="Can only specify one of post, file or image")
            ),
        ]

    def endpoint(self):
        return "assets"


del BaseCreateTest
