from abc import ABC, abstractmethod

from rest_framework.test import APIClient
from rest_framework import status

from ..utils.BaseTest import BaseTest, BulkCreateData


class BaseBulkCreateTest(BaseTest, ABC):
    @abstractmethod
    def get_valid_bulk_create_data_variations_for_admin(self, admin) -> [BulkCreateData]:
        return []

    @abstractmethod
    def get_invalid_bulk_create_data_variations_for_admin(self, admin) -> [BulkCreateData]:
        return []

    def get_valid_bulk_create_data_variations_for_consumer(self, consumer) -> [BulkCreateData]:
        return []

    def get_invalid_bulk_create_data_variations_for_consumer(self, consumer) -> [BulkCreateData]:
        return []

    def valid_bulk_create(self, bulk_create_data, access_token):
        response = self._bulk_create(bulk_create_data, access_token)

        if response.status_code != status.HTTP_201_CREATED:
            self.warn(f"Failed to create object with data: {bulk_create_data}, error: {response.data}",)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.validate_bulk_create_response_data(bulk_create_data, response.json)

        return response

    def validate_bulk_create_response_data(self, bulk_create_data, response_json):
        return True

    def test_success_with_admin(self):
        for i, create_data_variation in enumerate(self.get_valid_bulk_create_data_variations_for_admin(self.admin_one)):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_bulk_create(create_data_variation.request_data, self.admin_one_access_token)

    def test_fail_with_admin(self):
        for i, create_data_variation in enumerate(self.get_invalid_bulk_create_data_variations_for_admin(self.admin_one)):
            with self.subTest(msg=f"Variation {i + 1}"):
                response = self._bulk_create(create_data_variation.request_data, self.admin_one_access_token)
                if response.status_code != status.HTTP_400_BAD_REQUEST:
                    self.assertEqual(response.status_code, create_data_variation.response_code)

                if hasattr(create_data_variation.response_error, "value"):
                    self.assertEqual(str(response.data[create_data_variation.response_error.key][0]), create_data_variation.response_error.value)

    def test_success_with_consumer(self):
        consumer = self.get_consumer()

        if not consumer:
            return

        for i, create_data_variation in enumerate(self.get_valid_bulk_create_data_variations_for_consumer(consumer)):
            with self.subTest(msg=f"Variation {i + 1}"):
                self.valid_bulk_create(create_data_variation.request_data, self.get_consumer_access_token())

    def test_fail_with_consumer(self):
        consumer = self.get_consumer()

        if not consumer:
            return

        access_token = self.get_consumer_access_token()

        for i, create_data_variation in enumerate(self.get_invalid_bulk_create_data_variations_for_consumer(consumer)):
                with self.subTest(msg=f"Variation {i + 1}"):
                    response = self._bulk_create(create_data_variation.request_data, access_token)
                    if response.status_code != status.HTTP_400_BAD_REQUEST:
                        self.assertEqual(response.status_code, create_data_variation.response_code)

                    if hasattr(create_data_variation.response_error, "value"):
                        self.assertEqual(str(response.data[create_data_variation.response_error.key][0]), create_data_variation.response_error.value)

    def test_fail_with_admin_without_right_permission(self):
        permission_key = self.get_permission_key()

        if not permission_key:
            return

        self.remove_permission_of_current_admin(permission_key)

        response = self._bulk_create({}, self.admin_one_access_token)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(response.json["detail"], 'You do not have permission to access this')

    def test_fail_with_unauthenticated(self):
        self.unauthorized_account_test(self._bulk_create({}))

