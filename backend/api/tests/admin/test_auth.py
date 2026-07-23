import uuid

from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils import Data
from ..utils.manager import Auth

from freezegun import freeze_time


class AuthTest(TestCase):

    def setUp(self):
        admin_data = Data.valid_admin_data()

        self.email = admin_data["user"]["email"]
        self.password = admin_data["user"]["password"]

        self.admin = Auth.create_admin(data=admin_data)

        self.admin_access_token = Auth.get_access_token(self.admin.user)

    def test_login(self):
        response = Auth.login(self.email, self.password)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue("admin" in response.json)
        self.assertTrue("tokens" in response.json)

    def test_login_after_password_change(self):
        new_password = "89032Aa)"

        updated_login_data = {
            "user": {
                "password": new_password,
                "current_password": "Aow8rY%a00PLa"
            }
        }

        response = super()._patch(f"/admins/{self.admin.user.id}", updated_login_data,
                                  self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = Auth.login(self.email, new_password)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue("admin" in response.json)

        self.assertTrue("tokens" in response.json)

    def test_login_after_creating_new_admin_account(self):
        data = Data.valid_admin_data()
        email = data["user"]["email"]
        password = data["user"]["password"]

        super()._post("/admins", data, self.admin_access_token)

        response = Auth.login(email, password)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertTrue("admin" in response.json)

        self.assertTrue("tokens" in response.json)

    def test_success_with_request_reset_password(self):
        response = Auth.request_reset_password(self.email)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_success_reset_password_flow(self):
        response = Auth.request_reset_password(self.email)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.admin.refresh_from_db()

        password = "X4G0-acx"

        response = Auth.reset_password(self.email, self.admin.user.verification_code, password)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        Auth.login(self.email, password)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_failure_request_reset_password_before_threshold(self):
        from ...utils import DateUtils
        from datetime import timedelta

        response = Auth.request_reset_password(self.email)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.admin.refresh_from_db()
        self.assertIsNotNone(self.admin.user.verification_code_sent_at)

        reset_password_response = Auth.request_reset_password(self.email)
        self.assertEqual(reset_password_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(reset_password_response.json["error"], "Please wait 5 minutes between requests for a new code")

        request_verify_response = Auth.request_verify_email(self.admin_access_token)
        self.assertEqual(request_verify_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(request_verify_response.json["error"], "Please wait 5 minutes between requests for a new code")

        with freeze_time(DateUtils.now() + timedelta(minutes=5)):
            reset_response = Auth.request_reset_password(self.email)
            self.assertEqual(reset_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_failure_request_reset_password_without_required_data(self):
        response = super()._post("/user/request-reset-password", {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'Please provide an email')

    def test_failure_reset_password_without_required_data(self):
        response = Auth.request_reset_password("nonsense@email.tr")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'This email does not belong to a valid user')

    def test_failure_reset_password_with_wrong_verification_code(self):
        response = Auth.reset_password(self.email, "nonsense", "az5b`0dsA")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'Invalid verification code')

    def test_failure_reset_password_with_invalid_email(self):
        response = Auth.reset_password("nonsense@nonsense.ie", "nonsense", "ZPAF03-sa")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'This email does not belong to a user')

    def test_failure_reset_password_with_invalid_passwords(self):
        verification_code = str(uuid.uuid4())[:5]
        self.admin.user.verification_code = verification_code
        self.admin.user.save()

        password = "12345678"

        response = Auth.reset_password(self.email, verification_code, password)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'This password is too common.')

        password = "abc"

        response = Auth.reset_password(self.email, verification_code, password)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"],
                         'This password is too short. It must contain at least 8 characters.')

        password = "abcdefgh"

        response = Auth.reset_password(self.email, verification_code, password)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'This password is too common.')

        password = "Aa!89032da"

        response = Auth.reset_password(self.email, verification_code, password)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_logout(self):
        response = Auth.login(self.email, self.password)

        tokens = response.json["tokens"]
        access_token = "Bearer " + tokens["access"]
        refresh_token = tokens["refresh"]

        response = Auth.user_info(access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        Auth.logout(self.admin.user, access_token, refresh_token)

        response = Auth.user_info(access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = {
            "refresh": refresh_token
        }

        response = super()._post("/user/refresh-token", data, access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.json["detail"], "No refresh token found")

    def test_logout_twice(self):
        response = Auth.login(self.email, self.password)

        tokens = response.json["tokens"]
        access_token = "Bearer " + tokens["access"]
        refresh_token = tokens["refresh"]

        response = Auth.user_info(access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = Auth.logout(self.admin.user, access_token, refresh_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        response = Auth.logout(self.admin.user, access_token, refresh_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.json["detail"], "No refresh token found")

    def test_login_after_deleted(self):
        data = Data.valid_admin_data()
        email = data["user"]["email"]
        password = data["user"]["password"]

        response = super()._post("/admins", data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = super()._delete(f"/admins/{response.json['user']['id']}", self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        response = Auth.login(email, password)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(response.json["detail"], "Your account is no longer active")

    def test_failure_login(self):
        response = Auth.login("nonsense@email.ie", self.password)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'A user with this email and password combination does not exist.')
