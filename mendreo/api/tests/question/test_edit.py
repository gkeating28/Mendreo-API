from ..utils.manager import General
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError


from rest_framework import status


class EditTest(BaseEditTest):

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        # consumer not allow to edit questions
        return []

    def get_valid_edit_data_variations_for_admin(self, admin, agent) -> [EditData]:
        return [
            EditData(
                request_data={
                    "title": "new title"
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "suggested_responses": ["suggested", "responses"]
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
        obj.type = "boolean"
        obj.save()
        return [
            EditData(
                request_data={
                    "title": ""
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "suggested_responses": ["in", "valid"]
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
        ]

    def get_object(self, auth):
        return General.create_question()

    def endpoint(self):
        return "questions"


del BaseEditTest

