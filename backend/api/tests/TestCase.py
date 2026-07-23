from django.test import TransactionTestCase as DjangoTestCase
from rest_framework import status
from rest_framework.test import APIClient

from urllib.parse import urlencode
from .utils import Request
from .utils.manager import General

import json


class TestCase(DjangoTestCase):

    client = APIClient()

    @classmethod
    def _pre_setup(cls):
        super()._pre_setup()
        General.setup_db()

    def tearDown(self):
        super(TestCase, self).tearDown()

    @classmethod
    def _post(cls, endpoint, data, access_token="", multipart=False, query_params_dict=None, **kwargs):
        data = json.dumps(data)

        if query_params_dict is not None:
            endpoint += f"?{urlencode(query_params_dict)}"

        response = cls.client.post(
            endpoint,
            data,
            content_type="application/json",
            HTTP_AUTHORIZATION=access_token,
            **kwargs
        )

        if response.status_code != status.HTTP_204_NO_CONTENT:
            response.json = json.loads(response.content)

        return response

    @classmethod
    def _put(cls, endpoint, data, access_token="", multipart=False, **kwargs):
        data = json.dumps(data) if multipart is False else data
        content_type = "application/json" if multipart is False else None

        response = cls.client.put(
            endpoint,
            data,
            content_type=content_type,
            HTTP_AUTHORIZATION=access_token,
            **kwargs
        )

        if response.status_code != status.HTTP_204_NO_CONTENT:
            response.json = json.loads(response.content)

        return response

    @classmethod
    def _patch(cls, endpoint, data, access_token="", multipart=False, **kwargs):
        if multipart:
            response = Request.multipart_patch(
                endpoint,
                data,
                HTTP_AUTHORIZATION=access_token,
                **kwargs)

        else:
            response = cls.client.patch(
                endpoint,
                json.dumps(data),
                content_type="application/json",
                HTTP_AUTHORIZATION=access_token,
                **kwargs)

        response.json = json.loads(response.content)

        return response

    @classmethod
    def _get(cls, endpoint, query_params_dict=None, access_token="", include_json_response=True, **kwargs):

        if query_params_dict is not None:
            endpoint += f"?{urlencode(query_params_dict)}"

        response = cls.client.get(
            endpoint,
            content_type="application/json",
            HTTP_AUTHORIZATION=access_token,
            **kwargs
        )

        if include_json_response:
            response.json = json.loads(response.content)

        return response

    @classmethod
    def _delete(cls, endpoint, access_token="", data=None, **kwargs):

        response = cls.client.delete(
            endpoint,
            None if not data else json.dumps(data),
            content_type="application/json",
            HTTP_AUTHORIZATION=access_token,
            **kwargs
        )

        if response.status_code != status.HTTP_204_NO_CONTENT:
            response.json = json.loads(response.content)

        return response

    def unauthorized_account_test(self, action):
        response = action

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.assertEqual(response.json["detail"], 'Authentication credentials were not provided.')

    def not_found_test(self, action):
        response = action

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def method_not_allowed(self, action):
        response = action

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def permission_denied_test(self, action):
        response = action

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        error_message = response.json["detail"]

        is_error_message_correct = error_message.lower() in [
            "you do not have permission to perform this action.",
            "you do not have permission to access this",
            "only platform Admins accounts are able to access this",
            "only admin accounts are able to access this",
            "only super admin accounts are able to access this",
            "only consumer accounts are able to access this",
        ]

        self.assertTrue(is_error_message_correct)
