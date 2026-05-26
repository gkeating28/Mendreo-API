from ..utils.manager import General
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError

from ...utils import Constants, DateUtils

from rest_framework import status


class EditTest(BaseEditTest):

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        # consumer not allow to edit agent
        return []

    def get_valid_edit_data_variations_for_admin(self, admin, agent) -> [EditData]:
        return [
            EditData(
                request_data={
                    "title": "New Title"
                },
            ),
            EditData(
                request_data={
                    "subtitle": "New Subtitle"
                },
            ),
            EditData(
                request_data={
                    "body": "New Body"
                },
            ),
            EditData(
                request_data={
                    "status": Constants.POST_STATUS_PUBLISHED,
                    "published_at": "2025-01-01T00:00:00Z"
                },
            ),
        ]

    def get_invalid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        # consumer not allow to edit agent
        return [
            EditData(
                request_data={},
                response_error=ResponseError(
                    key="detail",
                    value="You do not have permission to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_invalid_edit_data_variations_for_admin(self, admin, obj) -> [EditData]:
        return [
            EditData(
                request_data={
                    "title": ""
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "body": None
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "status": Constants.POST_STATUS_PUBLISHED,
                    "published_at": None
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
        ]

    def get_object(self, auth):
        return General.create_post()

    def endpoint(self):
        return "posts"


del BaseEditTest

