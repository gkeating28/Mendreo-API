from .models import Admin

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..user.serializers import (
    UserCreateSerializer,
    UserEditSerializer,
    UserListSerializer,
)

from ..role.serializers import RoleListSerializer

from ..utils import Constants


class AdminCreateSerializer(CreateModelSerializer):
    user = UserCreateSerializer(
        nested_relation=True,
        related_name="user",
        model_name_in_related_object="user",
        create_before_model=True,
        edit_serializer=UserEditSerializer,
        create_serializer=UserCreateSerializer
    )

    class Meta:
        model = Admin
        fields = ["user", "role"]

    def validate(self, attrs):
        user_data = attrs['user']
        user_data["type"] = Constants.USER_TYPE_ADMIN
        return attrs



class AdminEditSerializer(EditModelSerializer):
    user = UserEditSerializer(
        nested_relation=True,
        required=False,
        related_name="user",
        model_name_in_related_object="user",
        edit_serializer=UserEditSerializer,
        create_serializer=UserCreateSerializer
    )

    class Meta:
        model = Admin
        fields = ["user", "role"]



class AdminListSerializer(ListModelSerializer):
    user = UserListSerializer()
    role = RoleListSerializer()

    class Meta:
        model = Admin
        fields = [
            "user",
            "role"
        ]

    @classmethod
    def get_select_related_fields(cls):
        return [
            "user",
            "role",
            "role__permissions"
        ]


class AdminDetailSerializer(AdminListSerializer):
    pass
