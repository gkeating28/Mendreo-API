import uuid

from unittest import mock

from ...tests.TestCase import TestCase

from rest_framework.test import APIClient
from rest_framework import status

from ..utils import Data
from ..utils.manager import Auth


class SocialAuthTest(TestCase):

    client = APIClient()

    def _post(self, data, **kwargs):
        response = super()._post("/user/login/social/jwt-pair-user/", data)

        return response

    def _test_apple(self):
        response = Auth.social_login("apple", object_response=False)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIsNotNone(response.json["consumer"])
        self.assertTrue(response.json["consumer"]["user"]["email_verified"])

    def test_google(self):
        response = Auth.social_login("google", object_response=False)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIsNotNone(response.json["consumer"])
        self.assertTrue(response.json["consumer"]["user"]["email_verified"])

    def test_failure_with_unsupported_provider(self):
        data = Data.valid_social_auth_data("does_not_exist")

        response = self._post(data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(response.json["detail"], "Backend not found")

    def test_failure_with_missing_data(self):
        response = self._post({})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json, "Provider is not specified")

        data = {
            "provider": "apple"
        }

        response = self._post(data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["code"][0], 'This field is required.')