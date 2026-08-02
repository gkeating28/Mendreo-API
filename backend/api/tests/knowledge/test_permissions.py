from ..utils.BaseTest import BaseTest
from ...role.models import Role
from ...utils import Constants


class KnowledgePermissionDefaultsTests(BaseTest):
    def endpoint(self):
        return "knowledge-fields"

    def test_default_roles_include_knowledge(self):
        Role.create_defaults()

        super_admin = Role.get_super_admin()
        self.assertEqual(
            list(super_admin.permissions.knowledge),
            Constants.SUPER_ADMIN_PERMISSIONS["knowledge"],
        )

        admin = Role.get_admin()
        self.assertEqual(
            list(admin.permissions.knowledge),
            Constants.ADMIN_PERMISSIONS["knowledge"],
        )

        viewer = Role.get_viewer()
        self.assertEqual(
            list(viewer.permissions.knowledge),
            Constants.VIEWER_PERMISSIONS["knowledge"],
        )
