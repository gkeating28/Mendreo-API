from abc import ABC, abstractmethod

from rest_framework.test import APIClient
from rest_framework import status

from ..utils.BaseTest import BaseTest, CreateData


class BaseCreateTest(BaseTest, ABC):

    @abstractmethod
    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        pass

    @abstractmethod
    def get_invalid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        pass

    @abstractmethod
    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        pass

    @abstractmethod
    def get_invalid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        pass

    def valid_create(self, create_data, access_token, response_code=status.HTTP_201_CREATED):
        response = self._create(create_data, access_token)

        if response.status_code != response_code:
            self.warn(f"Failed to create object with data: {create_data}, error: {response.data}",)

        self.assertEqual(response.status_code, response_code)
        self.validate_create_response_data(create_data, response.json)

        return response

    def validate_create_response_data(self, create_data, response_json):
        return True

    def test_success_with_consumer(self):
        for i, create_data_variation in enumerate(self.get_valid_create_data_variations_for_consumer(self.get_consumer())):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_create(create_data_variation.request_data, self.consumer_one_access_token, create_data_variation.response_code)

    def test_success_with_admin(self):
        for i, create_data_variation in enumerate(self.get_valid_create_data_variations_for_admin(self.admin_one)):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_create(create_data_variation.request_data, self.admin_one_access_token, create_data_variation.response_code)

    def test_fail_with_consumer(self):
        for i, create_data_variation in enumerate(self.get_invalid_create_data_variations_for_consumer(self.consumer_one)):
            with self.subTest(msg=f"Variation {i + 1}"):
                response = self._create(create_data_variation.request_data, self.consumer_one_access_token)
                self._test_fail_variation(response, create_data_variation)

    def test_fail_with_admin(self):
        for i, create_data_variation in enumerate(self.get_invalid_create_data_variations_for_admin(self.admin_one)):
            with self.subTest(msg=f"Variation {i + 1}"):
                response = self._create(create_data_variation.request_data, self.admin_one_access_token)
                self._test_fail_variation(response, create_data_variation)

    def _test_fail_variation(self, response, create_data_variation):
        self.assertEqual(response.status_code, create_data_variation.response_code)

        if hasattr(create_data_variation.response_error, "value"):
            error = response.json[create_data_variation.response_error.key]
            value = create_data_variation.response_error.value
            if isinstance(error, list):
                self.assertEqual(str(error[0]), create_data_variation.response_error.value)
            elif value:
                self.assertEqual(str(error), value)

    def test_fail_with_unauthenticated(self):
        self.unauthorized_account_test(self._create({}))