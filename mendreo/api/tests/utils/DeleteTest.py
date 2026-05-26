from abc import ABC, abstractmethod

from rest_framework.test import APIClient
from rest_framework import status

from ..utils.BaseTest import BaseTest


class BaseDeleteTest(BaseTest, ABC):

    @abstractmethod
    def get_object(self):
        pass

    def valid_delete(self, object, access_token):
        if not object:
            raise Exception("object is required")

        response = self._delete(object, access_token)

        if response.status_code != status.HTTP_204_NO_CONTENT:
            self.warn(f"Failed to delete object with id: {self.get_id_for_object(object)}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        return response

    def test_success_with_admin_one(self):
        self.valid_delete(self.get_object(), self.admin_one_access_token)

    def test_fail_with_wrong_id(self):
        self.not_found_test(self._delete(self.get_object_with_invalid_id(), self.admin_one_access_token))

    def test_fail_with_deleted(self):
        object = self.get_object()
        object.delete()

        self.not_found_test(self._delete(object, self.admin_one_access_token))

    def test_fail_with_unauthorized_account(self):
        self.unauthorized_account_test(self._delete(self.get_object_with_invalid_id()))


