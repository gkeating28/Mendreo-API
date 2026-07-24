from ..utils.Serializers import CreateModelSerializer, EditModelSerializer, ListModelSerializer
from ..permissions.serializers import (
    PermissionsCreateSerializer,
    PermissionsValidateSerializer,
    PermissionsListSerializer,
    PermissionsEditSerializer
)
from .models import Role


class RoleCreateSerializer(CreateModelSerializer):
    permissions = PermissionsValidateSerializer(write_only=True)

    class Meta:
        model = Role
        exclude = ["is_default"]

    def create(self, validated_data):
        permission_data = None
        if "permissions" in validated_data:
            permission_data = validated_data.pop("permissions")

        role = Role.objects.create(**validated_data)
        role.refresh_from_db()  # Ensure CharIDField is populated

        create_or_update_permission(role, permission_data or {})

        return role


class RoleEditSerializer(EditModelSerializer):
    permissions = PermissionsValidateSerializer(write_only=True)

    class Meta:
        model = Role
        fields = ["name", "permissions"]

    def validate(self, attrs):
        if self.instance.is_default:
            self.raise_validation_error("Role", "Default role cannot be edited")

        return attrs

    def update(self, instance, validated_data):
        permission_data = None
        if "permissions" in validated_data:
            permission_data = validated_data.pop("permissions")

        role = super(RoleEditSerializer, self).update(instance, validated_data)

        if permission_data:
            create_or_update_permission(role, permission_data)

        return role


class RoleListSerializer(ListModelSerializer):
    permissions = PermissionsListSerializer()

    class Meta:
        model = Role
        fields = "__all__"

    @staticmethod
    def optimise(queryset):
        return queryset.select_related("permissions")


class RoleDetailSerializer(RoleListSerializer):
    pass


def create_or_update_permission(role, permission_data):
    """Helper function to create or update permissions for a role"""
    data = (permission_data or {}).copy()
    if hasattr(role, "permissions"):
        serializer = PermissionsEditSerializer(instance=role.permissions, data=data, partial=True)
    else:
        data["role"] = role.id
        serializer = PermissionsCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
