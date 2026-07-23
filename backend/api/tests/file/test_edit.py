from ..utils.manager import General
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError

from ...utils import File as FileUtils

from rest_framework import status


class EditTest(BaseEditTest):

    def setUp(self):
        super().setUp()

    def get_valid_edit_data_variations_for_admin(self, admin, file) -> [EditData]:
        pre_signed_url = FileUtils.get_upload_link(file.url)
        response = General.upload_to_s3(pre_signed_url, "sample.pdf")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return [
            EditData(
                request_data={"token": file.token, "uploaded": True}
            )
        ]

    def get_invalid_edit_data_variations_for_admin(self, admin, file) -> [EditData]:
        return [
            EditData(
                request_data={"token": file.token, "uploaded": True},
                response_error=ResponseError(key="file", value="file is not uploaded")
            ),
            EditData(
                request_data={},
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "token": None
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "token": ""
                },
                response_code=status.HTTP_400_BAD_REQUEST
            ),
            EditData(
                request_data={
                    "token": "token"
                },
                response_code=status.HTTP_404_NOT_FOUND,
            ),
            EditData(
                request_data={
                    "token": file.token
                },
                response_error=ResponseError(key="uploaded", value="This field is required.")
            ),
            EditData(
                request_data={
                    "token": file.token,
                    "uploaded": None
                },
                response_error=ResponseError(key="uploaded", value="This field may not be null.")
            ),
            EditData(
                request_data={
                    "token": file.token,
                    "uploaded": False
                },
                response_code=status.HTTP_400_BAD_REQUEST
            )
        ]

    def validate_edit_response_data(self, object, edit_data, response_json, user):
        self.assertEqual(edit_data["uploaded"], response_json["uploaded"])

    def get_object(self, auth):
        # consumer not allowed to create file so we user admin
        return General.create_file("sample.pdf", user=self.admin_one.user)

    def get_edit_data_for_default_failure_tests(self):
        return {"token": self.get_object(self.admin_one).token}

    def endpoint(self):
        return "files"


del BaseEditTest

