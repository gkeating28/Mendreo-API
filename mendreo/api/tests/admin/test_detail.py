from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils.manager import Auth


class DetailTest(TestCase):

    def setUp(self):
        self.admin = Auth.create_admin()

        self.admin_access_token = Auth.get_access_token(self.admin.user)

        self.admin_2 = Auth.create_admin()

    def _get(self, id_, access_token="", **kwargs):
        response = super()._get(f"/admins/{id_}", access_token=access_token)

        return response

    def test_success_with_getting_own_account(self):
        response = self._get(self.admin.user_id, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["user"]["id"], self.admin.user_id)

    def test_success_with_account_created(self):
        response = self._get(self.admin_2.user_id, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json["user"]["id"], self.admin_2.user_id)

    def test_failure_with_deleted_by_admin(self):
        self.admin_2.delete()

        self.not_found_test(self._get(self.admin_2.user_id, self.admin_access_token))

    def test_failure_with_invalid_id(self):
        self.not_found_test(self._get(999, self.admin_access_token))

    def test_failure_with_unauthorized_account(self):
        self.unauthorized_account_test(self._get(111))
