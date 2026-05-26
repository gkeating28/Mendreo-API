from abc import ABC, abstractmethod

from rest_framework.test import APIClient
from rest_framework import status

from ..utils.BaseTest import BaseTest, EditData


class BaseEditTest(BaseTest, ABC):

    client = APIClient()

    @abstractmethod
    def get_object(self, auth):
        pass

    @abstractmethod
    def get_valid_edit_data_variations_for_admin(self, admin, obj) -> [EditData]:
        pass

    @abstractmethod
    def get_invalid_edit_data_variations_for_admin(self, admin, obj) -> [EditData]:
        pass

    def get_valid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        return []

    def get_invalid_edit_data_variations_for_consumer(self, consumer, obj) -> [EditData]:
        return []

    def valid_edit(self, object_, edit_data, access_token, user=None):
        response = self._update(object_, edit_data, access_token)

        object_.refresh_from_db()

        if response.status_code != status.HTTP_200_OK:
            self.warn(f"Failed to edit object: {object_} with data {edit_data} with response {response.content}",)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.get_object_id_from_data(response.data), self.get_id_for_object(object_))

        self.validate_edit_response_data(object_, edit_data, response.json, user)

    def validate_edit_response_data(self, object_, edit_data, response_json, user):

        for key, value in edit_data.items():
            comparison_value = response_json[key]

            if isinstance(comparison_value, dict):
                comparison_value = comparison_value["id"]

            if comparison_value != value:
                self.warn(f"Failed to edit object's {key} with value: {value}", )

            self.assertEqual(comparison_value, value)

    def test_success_with_admin(self):
        obj = self.get_object(self.admin_one)
        for i, edit_data_variation in enumerate(self.get_valid_edit_data_variations_for_admin(self.admin_one, obj)):
            with self.subTest(msg=f"Variation {i + 1}"):
                obj = edit_data_variation.request_object if edit_data_variation.request_object else obj
                self.valid_edit(obj, edit_data_variation.request_data, self.admin_one_access_token, self.admin_one.user)

    def test_fail_with_admin(self):
        obj = self.get_object(self.admin_one)
        for i, edit_data_variation in enumerate(self.get_invalid_edit_data_variations_for_admin(self.admin_one, obj)):
            with self.subTest(msg=f"Variation {i + 1}"):
                obj = edit_data_variation.request_object if edit_data_variation.request_object else obj
                response = self._update(obj, edit_data_variation.request_data, self.admin_one_access_token)

                self.assertEqual(response.status_code, edit_data_variation.response_code)

                if hasattr(edit_data_variation.response_error, "key"):
                    error = response.json[edit_data_variation.response_error.key]
                    if isinstance(error, list):
                        error = error[0]

                    self.assertEqual(error, edit_data_variation.response_error.value)

    def test_success_with_consumer(self):
        consumer = self.get_consumer()

        if not consumer:
            return

        obj = self.get_object(self.consumer_one)
        for i, edit_data_variation in enumerate(self.get_valid_edit_data_variations_for_consumer(consumer, obj)):
            with self.subTest(msg=f"Variation {i + 1}"):
                obj = edit_data_variation.request_object if edit_data_variation.request_object else obj
                self.valid_edit(obj, edit_data_variation.request_data, self.get_consumer_access_token(), consumer.user)

    def test_fail_with_consumer(self):

        obj = self.get_object(self.consumer_one)
        for i, edit_data_variation in enumerate(self.get_invalid_edit_data_variations_for_consumer(self.consumer_one, obj)):
            with self.subTest(msg=f"Variation {i + 1}"):
                obj = edit_data_variation.request_object if edit_data_variation.request_object else obj
                response = self._update(obj, edit_data_variation.request_data, self.consumer_one_access_token)

                if response.status_code != edit_data_variation.response_code:
                    self.warn(
                        f"Unexpected response to edit object: {obj} with data {edit_data_variation.request_data} with response {response.content}", )

                self.assertEqual(response.status_code, edit_data_variation.response_code)

                if hasattr(edit_data_variation.response_error, "key"):
                    error = response.json[edit_data_variation.response_error.key]
                    if isinstance(error, list):
                        error = error[0]

                    self.assertEqual(error, edit_data_variation.response_error.value)

    def get_edit_data_for_default_failure_tests(self):
        return {}

    def test_fail_with_deleted(self):
        object = self.get_object(self.admin_one)
        object.delete()

        self.not_found_test(self._update(object, self.get_edit_data_for_default_failure_tests(), self.admin_one_access_token))

    def test_fail_with_invalid_id(self):
        self.not_found_test(self._update(self.get_object_with_invalid_id(), self.get_edit_data_for_default_failure_tests(), self.admin_one_access_token))

    def test_fail_with_unauthorized_account(self):
        self.unauthorized_account_test(self._update(self.get_object_with_invalid_id(), self.get_edit_data_for_default_failure_tests()))
