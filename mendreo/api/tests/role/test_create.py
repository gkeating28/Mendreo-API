from ...tests.TestCase import TestCase
from rest_framework import status


class CreateTest(TestCase):
    def setUp(self):
        from ..utils.manager.Auth import get_platform_admin_access_token, get_or_create_admin

        self.admin = get_or_create_admin()
        self.admin_access_token = get_platform_admin_access_token(self.admin)

    def test_default_roles_created(self):
        from ...role.models import Role

       
        Role.create_defaults()

     
        roles = Role.objects.all()
        self.assertEqual(roles.count(), 3)

        role_names = ["Super Admin", "Admin", "Read Only"]
        for role in roles:
            self.assertIn(role.name, role_names)
            role_names.remove(role.name)

        self.assertEqual(len(role_names), 0)

    def test_super_admin_role_properties(self):
        """Test Super Admin role has correct properties"""
        from ...role.models import Role

        super_admin = Role.get_super_admin()


        self.assertTrue(super_admin.is_default)
        self.assertEqual(super_admin.name, "Super Admin")

     
        permissions = super_admin.permissions
        self.assertIn("view", permissions.users)
        self.assertIn("create", permissions.users)
        self.assertIn("edit", permissions.users)
        self.assertIn("delete", permissions.users)

        self.assertIn("view", permissions.exercises)
        self.assertIn("create", permissions.exercises)
        self.assertIn("edit", permissions.exercises)
        self.assertIn("delete", permissions.exercises)

    def test_admin_role_properties(self):
        from ...role.models import Role

        admin = Role.get_admin()


        self.assertFalse(admin.is_default)
        self.assertEqual(admin.name, "Admin")

       
        permissions = admin.permissions
        self.assertIn("view", permissions.users)
        self.assertNotIn("delete", permissions.users)

      
        self.assertIn("view", permissions.exercises)
        self.assertIn("create", permissions.exercises)
        self.assertIn("edit", permissions.exercises)
        self.assertNotIn("delete", permissions.exercises)

    def test_viewer_role_properties(self):
        from ...role.models import Role

        viewer = Role.get_viewer()


        self.assertFalse(viewer.is_default)
        self.assertEqual(viewer.name, "Read Only")

     
        permissions = viewer.permissions
        self.assertIn("view", permissions.users)
        self.assertNotIn("create", permissions.users)
        self.assertNotIn("edit", permissions.users)
        self.assertNotIn("delete", permissions.users)

    def test_list_roles(self):
        from ...role.models import Role


        Role.create_defaults()

        self.admin.role = Role.get_super_admin()
        self.admin.save()

        response = self._get(
            "/roles",
            access_token=self.admin_access_token
        )

        response_json = response.json
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response_json["results"]


        self.assertEqual(len(results), 3)

        role_names = ["Super Admin", "Admin", "Read Only"]
        for role in results:
            self.assertIn(role["name"], role_names)
            role_names.remove(role["name"])

        self.assertEqual(len(role_names), 0)

    def _assert_permissions_match(self, expected_permissions_dict, actual_permissions_obj):
        """Helper method to compare expected permissions dict with actual permissions object"""
        for permission_key, expected_values in expected_permissions_dict.items():
            actual_values = getattr(actual_permissions_obj, permission_key)

            for expected_value in expected_values:
                self.assertIn(
                    expected_value,
                    actual_values,
                    f"Expected '{expected_value}' to be in {permission_key} permissions"
                )

            for actual_value in actual_values:
                self.assertIn(
                    actual_value,
                    expected_values,
                    f"Unexpected permission '{actual_value}' found in {permission_key}"
                )

    def test_create_custom_role(self):
        from ...role.models import Role
        Role.create_defaults()
        self.admin.role = Role.get_super_admin()
        self.admin.save()

        custom_role_data = {
            "name": "Content Manager",
            "permissions": {
                "users": ["view"],
                "sessions": ["view"],
                "signups": [],
                "feedback": [],
                "exercises": ["view", "create", "edit"],
                "assets": ["view", "create"],
                "questions": ["view", "create", "edit"],
                "roles": [],
                "pii": []
            }
        }

        response = self._post(
            "/roles",
            custom_role_data,
            access_token=self.admin_access_token
        )

        response_json = response.json


        if response.status_code != status.HTTP_201_CREATED:
            print(f"Error creating role: {response_json}")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response_json["name"], "Content Manager")


        role = Role.objects.get(id=response_json["id"])
        self._assert_permissions_match(custom_role_data["permissions"], role.permissions)

    def test_invalid_permission_values_rejected(self):
        from ...role.models import Role

        Role.create_defaults()
        self.admin.role = Role.get_super_admin()
        self.admin.save()

        invalid_role_data = {
            "name": "Invalid Role",
            "permissions": {
                "exercises": ["invalid_permission", "view"]
            }
        }

        response = self._post(
            "/roles",
            invalid_role_data,
            access_token=self.admin_access_token
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
