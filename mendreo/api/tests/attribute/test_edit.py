from ..utils.manager import General
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError


from rest_framework import status


class EditTest(BaseEditTest):

    def test_fail_with_deleted(self):
        object = self.get_object(self.admin_one)
        object.delete()

        self.permission_denied_test(self._update(object, {}, self.admin_one_access_token))

    def test_fail_with_invalid_id(self):
        self.permission_denied_test(self._update(self.get_object_with_invalid_id(), {}, self.admin_one_access_token))

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        return [
            EditData(
                request_data={
                    "value": "New Answer"
                },
            ),
        ]

    def get_valid_edit_data_variations_for_admin(self, admin, agent) -> [EditData]:
        return []

    def get_invalid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        return [
            EditData(
                request_data={
                    "value": ""
                },
                response_error=ResponseError(
                    key="value",
                    value="This field may not be blank.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
        ]

    def get_invalid_edit_data_variations_for_admin(self, admin, obj) -> [EditData]:
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

    def get_object(self, auth):
        return General.create_attribute(consumer=self.consumer_one)

    def endpoint(self):
        return "attributes"


del BaseEditTest

