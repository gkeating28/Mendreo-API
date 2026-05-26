from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from ...utils import Constants

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
                    value="You do not have permission to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_post_data(),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        article_without_body = Data.valid_post_data()
        del article_without_body["body"]

        article_with_file = Data.valid_post_data()
        article_with_file["file"] = General.create_file().id

        video_no_file = Data.valid_post_data(type_=Constants.POST_TYPE_VIDEO)

        data_no_thumbnail = Data.valid_post_data()
        del data_no_thumbnail["thumbnail"]
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(key="title", value="This field is required.")
            ),

            CreateData(
                request_data={"title": "Title", "subtitle": "Subtitle", "type": "article"},
                response_error=ResponseError(key="banner", value="This field is required.")
            ),

            CreateData(
                request_data={"title": "Title", "banner": General.create_image().id},
                response_error=ResponseError(key="subtitle", value="This field is required.")
            ),

            CreateData(
                request_data=Data.valid_post_data(title=""),
                response_error=ResponseError(key="title", value="This field may not be blank.")
            ),

            CreateData(
                request_data=data_no_thumbnail,
                response_error=ResponseError(key="thumbnail", value="This field is required.")
            ),

            CreateData(
                request_data=video_no_file,
                response_error=ResponseError(key="file", value="This field is required.")
            ),

            CreateData(
                request_data=article_without_body,
                response_error=ResponseError(key="body", value="This field is required.")
            ),

            CreateData(
                request_data=article_with_file,
                response_error=ResponseError(key="file", value="This field cannot be specified for type: 'article'.")
            )
        ]

    def endpoint(self):
        return "posts"


del BaseCreateTest
