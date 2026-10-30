from rest_framework import status

from ...utils import Constants
from ..utils.manager import Auth
from ..TestCase import TestCase


class EditTest(TestCase):

    def _edit(self, data, access_token="", **kwargs):
        return super()._post("/settings", data, access_token=access_token)

    def test_basic(self):
        data = {"survey_enabled": False}

        response = self._edit(data, access_token=Auth.get_platform_admin_access_token())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.data["survey_enabled"], data["survey_enabled"])

    def test_onboarding_followup_lines(self):
        data = {
            "survey_enabled": True,
            "onboarding_followup_permission_ask": 'You said "{answer}" to "{question}".',
            "onboarding_followup_decline": "Alright.",
            "onboarding_followup_reask": "Say a bit more.",
            "onboarding_followup_chip_yes": "Go ahead",
            "onboarding_followup_chip_no": "Leave it",
        }
        token = Auth.get_platform_admin_access_token()
        response = self._edit(data, access_token=token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for key in (
            "onboarding_followup_permission_ask",
            "onboarding_followup_decline",
            "onboarding_followup_reask",
            "onboarding_followup_chip_yes",
            "onboarding_followup_chip_no",
        ):
            self.assertEqual(response.data[key], data[key])

        listed = self._get("/settings", access_token=token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        for key in data:
            if key == "survey_enabled":
                continue
            self.assertEqual(listed.json[key], data[key])
        self.assertEqual(
            listed.json["onboarding_followup_permission_ask"],
            data["onboarding_followup_permission_ask"],
        )
        self.assertNotEqual(
            data["onboarding_followup_decline"],
            Constants.KNOWLEDGE_FOLLOWUP_PERMISSION_DECLINE_ACK,
        )

    def test_prompt_keys_are_rejected(self):
        response = self._edit(
            {
                "survey_enabled": False,
                "general_prompt": "General prompt",
                "therapeutic_prompt": "Therapeutic prompt",
            },
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fail_as_company_member(self):
        self.permission_denied_test(self._edit({}, access_token=Auth.get_consumer_access_token()))

    def test_fail_as_anon(self):
        self.unauthorized_account_test(self._edit({}))
