from rest_framework import status

from ..utils.manager import Auth
from ..TestCase import TestCase


class EditTest(TestCase):

    def _edit(self, data, access_token="", **kwargs):
        return super()._post("/settings", data, access_token=access_token)

    def test_basic(self):
        data = {
            "survey_enabled": False,
            "general_prompt": "General prompt",
            "therapeutic_prompt": "Therapeutic prompt"
        }

        response = self._edit(data, access_token=Auth.get_platform_admin_access_token())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["survey_enabled"], data["survey_enabled"])
        self.assertEqual(response.data["general_prompt"], data["general_prompt"])
        self.assertEqual(response.data["therapeutic_prompt"], data["therapeutic_prompt"])

    def test_fail_as_company_member(self):
        self.permission_denied_test(self._edit({}, access_token=Auth.get_consumer_access_token()))

    def test_fail_as_anon(self):
        self.unauthorized_account_test(self._edit({}))
