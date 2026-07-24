from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils.manager import Auth, General


class ListTest(TestCase):

    def setUp(self):
        self.admin = General.get_or_create_admin()

        self.admin_access_token = Auth.get_access_token(self.admin.user)

        self.admin_2 = Auth.create_admin()

    def _get(self, query_params=None, access_token="", **kwargs):
        response = super()._get("/admins", query_params_dict=query_params, access_token=access_token)

        return response

    def test_success(self):
        response = self._get(access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json["results"]), 2)

    def test_filters(self):
        query_params_dict = {
            "search_term": "mendreo"
        }

        response = self._get(query_params_dict, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json["results"]), 0)

        query_params_dict = {
            "search_term": self.admin_2.user.first_name
        }

        response = self._get(query_params_dict, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(len(response.json["results"]), 1)
        self.assertEqual(response.json["results"][0]["user"]["id"], self.admin_2.user_id)

    def test_failure_with_unauthorized(self):
        self.unauthorized_account_test(self._get())