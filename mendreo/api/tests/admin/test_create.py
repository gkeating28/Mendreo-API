from ...tests.TestCase import TestCase

from rest_framework import status

from ...utils import Constants

from ..utils import Data
from ..utils.manager import Auth


class CreateTest(TestCase):

    def setUp(self):
        self.admin = Auth.create_admin()

        self.admin_access_token = Auth.get_access_token(self.admin.user)

    def _post(self, data, access_token="", **kwargs):
        response = super()._post("/admins", data, access_token)

        return response

    def test_success(self):
        data = Data.valid_admin_data()
        data["user"]["phone_country_code"] = "+353"
        data["user"]["phone_number"] = "123456789"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user_data = data["user"]

        user = response.json["user"]

        self.assertEqual(user["type"], Constants.USER_TYPE_ADMIN)
        self.assertTrue(user["id"].startswith("usr_"))
        self.assertEqual(user_data["first_name"], user["first_name"])
        self.assertEqual(user_data["last_name"], user["last_name"])
        self.assertEqual(user_data["email"], user["email"])
        self.assertEqual(user_data["phone_country_code"], user["phone_country_code"])
        self.assertEqual(user_data["phone_number"], user["phone_number"])

    def test_failure_with_invalid_phone_number(self):
        data = Data.valid_admin_data()
        data["user"]["phone_country_code"] = "+353"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["User"][0], "'phone_number' or 'phone_country_code' cannot be null if one of them is provided")

        data["user"]["phone_country_code"] = None
        data["user"]["phone_number"] = "+353"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["User"][0],
                         "'phone_number' or 'phone_country_code' cannot be null if one of them is provided")

    def test_failure_with_invalid_password(self):
        data = Data.valid_admin_data()
        data["user"]["password"] = "123456"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["password"][0], 'This password is too short. It must contain at least 8 characters.')

        data["user"]["password"] = "12345678"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["password"][0],
                         'This password is too common.')

    def test_failure_with_existing_email(self):
        data = Data.valid_admin_data()
        data["user"]["email"] = self.admin.user.email

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["email"][0], 'user with this email already exists.')

    def test_failure_with_invalid_email(self):
        data = Data.valid_admin_data()
        data["user"]["email"] = "b@ee.i"

        response = self._post(data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"]["email"][0], 'Enter a valid email address.')

    def test_failure_without_required_data(self):
        response = self._post({}, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["user"][0], "This field is required.")

    def test_failure_with_unauthorized_account(self):
        self.unauthorized_account_test(self._post({}))


