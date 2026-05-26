from ...tests.TestCase import TestCase

from rest_framework import status

from ..utils.manager import Auth


class DeleteTest(TestCase):

    def setUp(self):
        self.admin = Auth.create_admin()

        self.admin_access_token = Auth.get_access_token(self.admin.user)

        self.admin_2 = Auth.create_admin()

    def _delete(self, id_, access_token="", **kwargs):
        response = super()._delete(f"/admins/{id_}", access_token)

        return response

    def test_success_with_account_belongs_to_someone_else(self):
        response = self._delete(self.admin_2.user_id, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_failure_with_own_account(self):
        response = self._delete(self.admin.user_id, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(response.json["detail"], 'You cannot delete your own account')

    def test_failure_with_wrong_id(self):
        self.not_found_test(self._delete(999, self.admin_access_token))

    def test_failure_with_deleted(self):
        self.admin_2.delete()

        self.not_found_test(self._delete(self.admin_2.user_id, self.admin_access_token))

    def test_failure_with_unauthorized(self):
        self.unauthorized_account_test(self._delete(999))
