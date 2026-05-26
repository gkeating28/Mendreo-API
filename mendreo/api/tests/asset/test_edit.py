from ..utils.manager import General
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError

from ...file.models import File

from rest_framework import status


class EditTest(BaseEditTest):

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        # consumer not allow to edit agent
        return []

    def get_valid_edit_data_variations_for_admin(self, admin, agent) -> [EditData]:
        return [
            EditData(
                request_data={
                    "name": "new name"
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "context": "new context"
                },
                response_code=status.HTTP_400_BAD_REQUEST
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
                    "name": ""
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "description": ""
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
        ]

    def validate_edit_response_data(self, object_, edit_data, response_json, user):
        if "context" in edit_data:
            self.assertEqual(object_.context, edit_data["context"])
            del edit_data["context"]

        return super(EditTest, self).validate_edit_response_data(object_, edit_data, response_json, user)


    def get_object(self, auth):
        return General.create_agent()

    def endpoint(self):
        return "agents"


del BaseEditTest

