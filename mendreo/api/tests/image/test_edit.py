from ..utils.manager import General, Auth
from ..utils.EditTest import BaseEditTest, EditData
from ..utils.BaseTest import ResponseError

from ...image.models import Image
from ...utils import File as FileUtils

from rest_framework import status


class EditTest(BaseEditTest):

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        response = General.upload_to_s3(self.pre_signed_url, "sample.pdf")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return [
            EditData(
                request_data={"token": obj.token, "uploaded": True}
            )
        ]

    def get_valid_edit_data_variations_for_admin(self, admin, image) -> [EditData]:
        pre_signed_url = FileUtils.get_upload_link(image.original)
        response = General.upload_to_s3(pre_signed_url, "sample.pdf")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return [
            EditData(
                request_data={"token": image.token, "uploaded": True}
            )
        ]

    def get_invalid_edit_data_variations_for_consumer(self, consumer, image) -> [EditData]:
        # see amin for invalid variations
        return []

    def get_invalid_edit_data_variations_for_admin(self, admin, image) -> [EditData]:
        return [
            EditData(
                request_data={"token": image.token, "uploaded": True},
                response_error=ResponseError(key="image", value="image is not uploaded")
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
                    "token": image.token
                },
                response_error=ResponseError(key="uploaded", value="This field is required.")
            ),
            EditData(
                request_data={
                    "token": image.token,
                    "uploaded": None
                },
                response_error=ResponseError(key="uploaded", value="This field may not be null.")
            ),
            EditData(
                request_data={
                    "token": image.token,
                    "uploaded": False
                },
                response_code=status.HTTP_400_BAD_REQUEST
            )
        ]

    def validate_edit_response_data(self, object, edit_data, response_json, user):
        self.assertEqual(edit_data["uploaded"], response_json["uploaded"])

    def get_object(self, auth):

        response_json = General.create_image(
            access_token=Auth.get_access_token(auth.user),
            object_response=False
        )

        return Image.objects.get(id=response_json["image"]["id"])

    def get_edit_data_for_default_failure_tests(self):
        image = self.get_object(self.admin_one)
        return {"token": image.token}

    def endpoint(self):
        return "images"


del BaseEditTest

