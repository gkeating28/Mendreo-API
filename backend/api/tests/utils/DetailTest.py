from abc import ABC, abstractmethod

from ...utils import Constants

from rest_framework.test import APIClient

from rest_framework import status

from ..utils.BaseTest import BaseTest


class BaseDetailTest(BaseTest, ABC):

    @abstractmethod
    def get_object(self):
        pass

    def test_success(self):
        obj = self.get_object()

        response = self._get(obj, self.admin_one_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.get_object_id_from_data(response.data), self.get_id_for_object(obj))

        self.validate_detail_response_data(obj, self.admin_one.user, response.json)

    def test_success_with_consumer(self):
        obj = self.get_object()

        response = self._get(obj, self.consumer_one_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.get_object_id_from_data(response.data), self.get_id_for_object(obj))

        self.validate_detail_response_data(obj, self.consumer_one.user, response.json)

    def test_fail_with_deleted(self):
        obj = self.get_object()
        obj.delete()

        self.not_found_test(self._get(obj, self.admin_one_access_token))

    def test_fail_with_invalid_id(self):
        self.not_found_test(self._get(self.get_object_with_invalid_id(), self.admin_one_access_token))

    def validate_detail_response_data(self, obj, user, response_json):
        pass

    def test_fail_with_unauthorized_account(self):
        self.unauthorized_account_test(self._get(self.get_object_with_invalid_id()))

