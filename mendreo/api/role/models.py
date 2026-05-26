from django.db import models
from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField
from ..utils import Constants


class Role(SmartModel):

    id = CharIDField(primary_key=True, prefix="rol_")

    name = models.CharField(max_length=255)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Role: {}".format(self.name)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "roles"

    @staticmethod
    def _get_or_create(name, is_default, permissions):
        from ..permissions.models import Permissions

        role, created = Role.objects.get_or_create(
            name=name,
            defaults={
                'is_default': is_default
            }
        )

        if created:
            Permissions.objects.create(
                role=role,
                **permissions
            )

        return role

    @staticmethod
    def get_super_admin():
        return Role._get_or_create("Super Admin", True, Constants.SUPER_ADMIN_PERMISSIONS)

    @staticmethod
    def get_admin():
        return Role._get_or_create("Admin", False, Constants.ADMIN_PERMISSIONS)

    @staticmethod
    def get_viewer():
        return Role._get_or_create("Read Only", False, Constants.VIEWER_PERMISSIONS)

    @staticmethod
    def create_defaults():
        Role.get_super_admin()
        Role.get_admin()
        Role.get_viewer()
