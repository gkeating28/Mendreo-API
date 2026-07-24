from ...tests.TestCase import TestCase
from rest_framework import status


class EditTest(TestCase):
    def setUp(self):
        from ..utils.manager.Auth import get_platform_admin_access_token, get_or_create_admin
        from ...role.models import Role

        self.admin = get_or_create_admin()
        self.admin_access_token = get_platform_admin_access_token(self.admin)

        Role.create_defaults()
        self.admin.role = Role.get_super_admin()
        self.admin.save()

        custom_role_data = {
            "name": "Test Custom Role",
            "permissions": {
                "users": ["view"],
                "sessions": ["view"],
                "signups": [],
                "feedback": [],
                "exercises": ["view", "create"],
                "assets": ["view"],
                "questions": ["view"],
                "roles": [],
                "pii": []
            }
        }

        response = self._post("/roles", custom_role_data, self.admin_access_token)
        self.custom_role_id = response.json["id"]

    def _patch(self, id_, data, access_token=""):
        response = super()._patch(f"/roles/{id_}", data, access_token)
        return response

    def _delete(self, id_, access_token=""):
        response = super()._delete(f"/roles/{id_}", access_token)
        return response

    def test_get_single_role_detail(self):
        """Test getting details of a single role"""
        response = self._get(f"/roles/{self.custom_role_id}", access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["id"], self.custom_role_id)
        self.assertEqual(response.json["name"], "Test Custom Role")
        self.assertIn("permissions", response.json)

    def test_edit_custom_role_name(self):
        """Test editing a custom role's name"""
        updated_data = {
            "name": "Updated Custom Role"
        }

        response = self._patch(self.custom_role_id, updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["name"], "Updated Custom Role")

    def test_edit_custom_role_permissions(self):
        """Test editing a custom role's permissions"""
        from ...role.models import Role

        updated_data = {
            "name": "Updated Custom Role",
            "permissions": {
                "users": ["view", "create"],
                "sessions": ["view", "create", "edit"],
                "signups": ["view"],
                "feedback": ["view"],
                "exercises": ["view", "create", "edit", "delete"],
                "assets": ["view", "create", "edit"],
                "questions": ["view", "create"],
                "roles": ["view"],
                "pii": []
            }
        }

        response = self._patch(self.custom_role_id, updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json["name"], "Updated Custom Role")


        role = Role.objects.get(id=self.custom_role_id)
        self.assertIn("view", role.permissions.users)
        self.assertIn("create", role.permissions.users)
        self.assertIn("edit", role.permissions.sessions)
        self.assertIn("delete", role.permissions.exercises)

    def test_fail_edit_default_role(self):
        """Test that editing a default role fails"""
        from ...role.models import Role

        super_admin_role = Role.get_super_admin()

        updated_data = {
            "name": "Trying to Edit Super Admin"
        }

        response = self._patch(super_admin_role.id, updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Default role cannot be edited", str(response.json))

    def test_fail_edit_role_with_invalid_permissions(self):
        """Test that editing with invalid permission values fails"""
        updated_data = {
            "permissions": {
                "exercises": ["invalid_action", "view"]
            }
        }

        response = self._patch(self.custom_role_id, updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_custom_role_success(self):
        """Test deleting a custom role"""
        from ...role.models import Role


        role_data = {
            "name": "Role to Delete",
            "permissions": {
                "users": ["view"],
                "sessions": [],
                "signups": [],
                "feedback": [],
                "exercises": [],
                "assets": [],
                "questions": [],
                "roles": [],
                "pii": []
            }
        }

        create_response = self._post("/roles", role_data, self.admin_access_token)
        role_id = create_response.json["id"]

        delete_response = self._delete(role_id, access_token=self.admin_access_token)

        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Role.objects.filter(id=role_id).exists())

    def test_fail_delete_default_role(self):
        """Test that deleting a default role fails"""
        from ...role.models import Role

        super_admin_role = Role.get_super_admin()

        response = self._delete(super_admin_role.id, access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot delete the default role", str(response.json).lower())

    def test_delete_admin_role_success(self):
        """Test that deleting the Admin role succeeds (is_default=False)"""
        from ...role.models import Role

        admin_role = Role.get_admin()


        response = self._delete(admin_role.id, access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_viewer_role_success(self):
        """Test that deleting the Read Only role succeeds (is_default=False)"""
        from ...role.models import Role

        viewer_role = Role.get_viewer()

        response = self._delete(viewer_role.id, access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_edit_role_partial_permissions(self):
        """Test editing only specific permission fields"""
        updated_data = {
            "permissions": {
                "exercises": ["view", "create", "edit", "delete"]
            }
        }

        response = self._patch(self.custom_role_id, updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        from ...role.models import Role
        role = Role.objects.get(id=self.custom_role_id)
        self.assertEqual(len(role.permissions.exercises), 4)

    def test_fail_get_nonexistent_role(self):
        """Test getting a non-existent role returns 404"""
        response = self._get("/roles/rol_nonexistent123", access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_fail_edit_nonexistent_role(self):
        """Test editing a non-existent role returns 404"""
        updated_data = {
            "name": "Updated Name"
        }

        response = self._patch("rol_nonexistent123", updated_data, self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_fail_delete_nonexistent_role(self):
        """Test deleting a non-existent role returns 404"""
        response = self._delete("rol_nonexistent123", access_token=self.admin_access_token)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_edit_without_authentication(self):
        """Test that editing without authentication fails"""
        updated_data = {
            "name": "Updated Name"
        }

        response = self._patch(self.custom_role_id, updated_data, access_token="")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_without_authentication(self):
        """Test that deleting without authentication fails"""
        response = self._delete(self.custom_role_id, access_token="")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
