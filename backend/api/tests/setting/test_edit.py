from rest_framework import status

from ...utils import Constants
from ..utils.manager import Auth
from ..TestCase import TestCase


class EditTest(TestCase):

    def _edit(self, data, access_token="", **kwargs):
        return super()._post("/settings", data, access_token=access_token)

    def test_thin_answer_hint_enabled(self):
        token = Auth.get_platform_admin_access_token()
        listed = self._get("/settings", access_token=token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertIs(listed.json["thin_answer_hint_enabled"], True)

        turned_off = self._edit(
            {"survey_enabled": True, "thin_answer_hint_enabled": False},
            access_token=token,
        )
        self.assertEqual(turned_off.status_code, status.HTTP_200_OK, turned_off.data)
        self.assertIs(turned_off.data["thin_answer_hint_enabled"], False)
        listed = self._get("/settings", access_token=token)
        self.assertIs(listed.json["thin_answer_hint_enabled"], False)

        turned_on = self._edit(
            {"survey_enabled": True, "thin_answer_hint_enabled": True},
            access_token=token,
        )
        self.assertEqual(turned_on.status_code, status.HTTP_200_OK, turned_on.data)
        self.assertIs(turned_on.data["thin_answer_hint_enabled"], True)

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

    def test_insights_values_save(self):
        data = {
            "survey_enabled": True,
            "insights_enabled": False,
            "insights_pool_cap": 10,
            "insights_shown_count": 3,
            "insights_recent_runs": 6,
            "insights_min_pool_before_shuffle": 4,
            "insights_max_length": 30,
            "insights_batch_size": 2,
        }
        token = Auth.get_platform_admin_access_token()
        response = self._edit(data, access_token=token)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        for key, value in data.items():
            if key == "survey_enabled":
                continue
            self.assertEqual(response.data[key], value)

        listed = self._get("/settings", access_token=token)
        self.assertEqual(listed.status_code, status.HTTP_200_OK, listed.json)
        for key, value in data.items():
            if key == "survey_enabled":
                continue
            self.assertEqual(listed.json[key], value)

    def test_insights_values_are_rejected(self):
        token = Auth.get_platform_admin_access_token()
        cases = (
            ({"insights_recent_runs": 0}, "insights_recent_runs"),
            (
                {"insights_pool_cap": 3, "insights_shown_count": 4},
                "insights_pool_cap",
            ),
            (
                {
                    "insights_pool_cap": 12,
                    "insights_shown_count": 6,
                    "insights_min_pool_before_shuffle": 5,
                },
                "insights_min_pool_before_shuffle",
            ),
            (
                {"insights_pool_cap": 12, "insights_batch_size": 13},
                "insights_batch_size",
            ),
        )
        for extra, error_key in cases:
            response = self._edit(
                {"survey_enabled": True, **extra},
                access_token=token,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, extra)
            self.assertIn(error_key, response.json, extra)

    def test_insights_instruction_is_rejected(self):
        response = self._edit(
            {
                "survey_enabled": True,
                "insights_instruction": "Write something else.",
            },
            access_token=Auth.get_platform_admin_access_token(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json["insights_instruction"],
            ["Save this text as a prompt version, not a setting."],
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
