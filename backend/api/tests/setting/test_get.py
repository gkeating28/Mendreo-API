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

    def test_insights_defaults(self):
        response = self._get(Auth.get_platform_admin_access_token())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json
        self.assertIs(data["insights_enabled"], True)
        self.assertEqual(data["insights_pool_cap"], Constants.DEFAULT_INSIGHTS_POOL_CAP)
        self.assertEqual(data["insights_shown_count"], Constants.DEFAULT_INSIGHTS_SHOWN_COUNT)
        self.assertEqual(data["insights_recent_runs"], Constants.DEFAULT_INSIGHTS_RECENT_RUNS)
        self.assertEqual(
            data["insights_min_pool_before_shuffle"],
            Constants.DEFAULT_INSIGHTS_MIN_POOL_BEFORE_SHUFFLE,
        )
        self.assertEqual(data["insights_max_length"], Constants.DEFAULT_INSIGHTS_MAX_LENGTH)
        self.assertEqual(data["insights_batch_size"], Constants.DEFAULT_INSIGHTS_BATCH_SIZE)

    def test_fail_as_company_member(self):
        self.permission_denied_test(self._get(access_token=Auth.get_consumer_access_token()))

    def test_fail_as_anon(self):
        self.unauthorized_account_test(self._get())