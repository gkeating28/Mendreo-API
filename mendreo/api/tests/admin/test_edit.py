from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils import Data
from ..utils.manager import Auth


class EditTest(TestCase):

    def setUp(self):
        admin_data = Data.valid_admin_data()

        self.email = admin_data["user"]["email"]

        self.password = admin_data["user"]["password"]

        self.admin = Auth.create_admin(data=admin_data)

        self.admin_access_token = Auth.get_access_token(self.admin.user)

        self.admin_2 = Auth.create_admin()

    def _patch(self, id_, data, access_token="", **kwargs):
        response = super()._patch(f"/admins/{id_}", data, access_token)

        return response

    def test_success_basic_details(self):
        data = {
            "user": {
                "first_name": "new_first_name",
                "type": "staff"
            },
        }

        response = self._patch(self.admin.user_id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["user"]["first_name"], data["user"]["first_name"])
        self.assertNotEqual(response.json["user"]["type"], data["user"]["type"])

    def test_with_updating_email_and_password_and_logging_in(self):
        new_email = "new@email.ie"
        new_password = "E3^xyzf89"

        data = {
            "user": {
                "email": new_email,
                "password": new_password,
                "current_password": Data.valid_admin_data()["user"]["password"],
            },
        }

        response = self._patch(self.admin.user_id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["user"]["email"], data["user"]["email"])

        response = Auth.login(new_email, new_password)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["admin"]["user"]["email"], data["user"]["email"])
        self.assertEqual(response.json["admin"]["user"]["id"], self.admin.user_id)

    # todo: fix later
    def test_existing_email_for_same_user(self):
        email = self.admin.user.email
        data = {
            "user": {
                "email": email
            },
        }

        response = self._patch(self.admin.user_id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["user"]["email"],  email)

    def test_success_with_editing_account_belongs_to_someone_else(self):

        data = {
            "user": {
                "first_name": "Keith"
            }
        }

        response = self._patch(self.admin_2.user_id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.admin_2.refresh_from_db()
        self.assertEqual(self.admin_2.user.full_name, f"{data['user']['first_name']} {self.admin_2.user.last_name}")

    def test_failure_with_using_email_belongs_to_different_user(self):
        data = {
            "user": {
                "email": self.admin_2.user.email
            }
        }

        response = self._patch(self.admin.user_id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["email"][0], 'A user with this email already exists.')

    def test_failure_changing_password_without_required_data(self):
        data = {
            "user": {
                "password": "A9SD_+abc",
            },
        }

        response = self._patch(self.admin.user.id, data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.data[0], 'Please include current_password in order to update your password')

    def test_failure_with_invalid_account(self):
        response = self._patch(999, {}, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.json["detail"], "An object with this id does not exist")

    def test_failure_with_deleted_account(self):
        response = self._patch(999, {}, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.json["detail"], "An object with this id does not exist")

    def test_failure_with_unauthorized_account(self):
        self.unauthorized_account_test(self._patch(999, {}))
