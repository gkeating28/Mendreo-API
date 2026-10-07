from rest_framework import serializers
from rest_framework.serializers import CharField

from ..utils.Serializers import CreateModelSerializer, EditModelSerializer, ListModelSerializer, ValidateModelSerializer
from ..utils import Constants, Exception, Message
from .models import Permissions


class PermissionsCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Permissions
        fields = "__all__"


class PermissionsValidateSerializer(ValidateModelSerializer):

    class Meta:
        model = Permissions
        exclude = ["role"]

    def validate(self, attrs):
        permission_values = Constants.ALL_PERMISSIONS

        valid_resources = [
            "users", "sessions", "signups", "feedback",
            "exercises", "assets", "questions", "roles", "pii", "knowledge",
            "knowledge_sources",
        ]

        for key, permissions in attrs.items():
            if key not in valid_resources:
                continue

            if not isinstance(permissions, list):
                continue

            allowed = permission_values
            if key == "knowledge_sources":
                allowed = Constants.KNOWLEDGE_SOURCES_PERMISSIONS

            for permission in permissions:
                if permission not in allowed:
                    raise serializers.ValidationError({
                        "permissions": {
                            key: f"'{permission}' value is not permitted, must be one of {allowed}"
                        }
                    })

        return attrs


class PermissionsEditSerializer(EditModelSerializer):

    class Meta:
        model = Permissions
        exclude = ["role"]


class PermissionsListSerializer(ListModelSerializer):

    class Meta:
        model = Permissions
        fields = "__all__"


class PermissionsDetailSerializer(PermissionsListSerializer):
    pass
