from abc import ABC, abstractmethod

from rest_framework import status

from .manager import Auth

from ..utils.BaseTest import BaseTest, QueryParamsData


class BaseListTest(BaseTest, ABC):

    def setUp(self):
        super(BaseListTest, self).setUp()
        self.objects = self.get_objects()

    @abstractmethod
    def get_objects(self):
        pass

    def get_objects_no(self):
        return len(self.objects)

    def get_valid_query_param_variations_for_admin(self, admin, objects) -> [QueryParamsData]:
        return []

    def get_invalid_query_param_variations_for_admin(self, admin, objects) -> [QueryParamsData]:
        return []

    def get_valid_query_param_variations_for_consumer(self, consumer, objects) -> [QueryParamsData]:
        return []

    def get_invalid_query_param_variations_for_consumer(self, consumer, objects) -> [QueryParamsData]:
        return []

    def valid_list(self, query_params_data, access_token, results_no=1, results_match_data=[], user=None):
        response = self._list(access_token, query_params_data)

        if response.status_code != status.HTTP_200_OK:
            self.warn(f"Failed to list objects with query params {query_params_data}",)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data

        if "results" in response.data:
            results = response.data["results"]

        if len(results) != results_no:
            self.warn(f"Unexpected no of results: {len(results)}, expected: {results_no} for query params: {query_params_data}")

        self.assertEqual(len(results), results_no)

        for i, result_match_data in enumerate(results_match_data):
            result = results[i]
            for key, value in result_match_data.items():
                self.assertEqual(result[key], value)

        self.validate_list_response_data(query_params_data, access_token, results_no, results_match_data, user)

        return response

    def validate_list_response_data(self, query_params_data, access_token, results_no, results_match_data, user):
        pass

    def test_admin_no_filters(self):
        self.valid_list({}, self.admin_one_access_token, self.get_objects_no(), user=self.admin_one.user)

    def test_admin_filters(self):
        for i, query_params_data in enumerate(self.get_valid_query_param_variations_for_admin(self.admin_one, self.objects)):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_list(query_params_data.query_params, self.admin_one_access_token, query_params_data.results_no, query_params_data.results_match_data, user=self.admin_one.user)

    def test_fail_invalid_filters(self):
        for i, query_params_data in enumerate(self.get_invalid_query_param_variations_for_admin(self.admin_one, self.objects)):
            with self.subTest(msg=f"Variation {i + 1}"):
                response = self._list(self.admin_one_access_token, query_params_data.query_params)
                self.assertEqual(response.status_code, query_params_data.response_code)

                if hasattr(query_params_data.response_error, "key"):
                    self.assertEqual(str(response.data[query_params_data.response_error.key]),
                                     query_params_data.response_error.value)

    def test_consumer_no_filters(self):
        self.valid_list({}, self.consumer_one_access_token, self.get_objects_no(), user=self.consumer_one.user)

    def test_consumer_filters(self):

        for i, query_params_data in enumerate(self.get_valid_query_param_variations_for_consumer(self.consumer_one, self.objects)):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_list(query_params_data.query_params, self.consumer_one_access_token, query_params_data.results_no, query_params_data.results_match_data, user=self.consumer_one.user)

    def test_fail_invalid_consumer_filters(self):

        for i, query_params_data in enumerate(self.get_invalid_query_param_variations_for_consumer(self.consumer_one, self.objects)):
            with self.subTest(msg=f"Variation {i + 1}"):
                response = self._list(self.consumer_one_access_token, query_params_data.query_params)
                self.assertEqual(response.status_code, query_params_data.response_code)

                if hasattr(query_params_data.response_error, "key"):
                    self.assertEqual(str(response.data[query_params_data.response_error.key]),
                                     query_params_data.response_error.value)

    def test_fail_with_unauthenticated(self):
        self.unauthorized_account_test(self._list())