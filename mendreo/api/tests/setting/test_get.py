from rest_framework import status

from ...utils import Constants

from ..utils.manager import Auth
from ...tests.TestCase import TestCase


class GetTest(TestCase):

    def _get(self, access_token="", **kwargs):
        return super()._get("/settings", access_token=access_token)

    def test_basic(self):
        response = self._get(Auth.get_platform_admin_access_token())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json

        self.assertTrue(data["survey_enabled"])
        self.assertEqual(data["general_prompt"], Constants.PROMPT_GENERAL_GOALS)
        self.assertEqual(data["therapeutic_prompt"], Constants.PROMPT_THERAPEUTIC_INSTRUCTIONS)

    def test_fail_as_company_member(self):
        self.permission_denied_test(self._get(access_token=Auth.get_consumer_access_token()))

    def test_fail_as_anon(self):
        self.unauthorized_account_test(self._get())