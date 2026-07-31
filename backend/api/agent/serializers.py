from .models import Agent

from ..user.serializers import UserMinSerializer
from ..image.serializers import ImageListSerializer

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..utils import Constants


class AgentCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Agent
        fields = [
            "name",
            "avatar",
            "default",
            "context",
            "created_by",
            "description",
            "model",
        ]

    def validate_created_by(self, created_by):
        if created_by.type != Constants.USER_TYPE_ADMIN:
            self.raise_validation_error("created_by", "must be of type 'admin'")

        return created_by

    def validate_model(self, value):
        if value is not None and not str(value).strip():
            self.raise_validation_error("model", "This field may not be blank.")
        return value

    def validate(self, attrs):
        default = attrs.get("default")

        if default:
            Agent.objects.update(default=False)

        return attrs


class AgentEditSerializer(EditModelSerializer):

    class Meta:
        model = Agent
        fields = [
            "name",
            "avatar",
            "default",
            "context",
            "description",
            "model",
        ]

    def validate_model(self, value):
        if value is not None and not str(value).strip():
            self.raise_validation_error("model", "This field may not be blank.")
        return value

    def validate(self, attrs):
        default = attrs.get("default", self.instance.default)

        if default:
            Agent.objects.update(default=False)

        return attrs


class AgentListSerializer(ListModelSerializer):

    avatar = ImageListSerializer()

    class Meta:
        model = Agent
        fields = [
            "id",
            "name",
            "avatar",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return ["avatar"]


class AgentDetailSerializer(AgentListSerializer):

    class Meta(AgentListSerializer.Meta):
        AgentListSerializer.Meta.fields += [
            "description",
        ]


class AgentAdminListSerializer(AgentListSerializer):

    created_by = UserMinSerializer()

    class Meta(AgentListSerializer.Meta):
        fields = [
            "id",
            "name",
            "avatar",
            "default",
            "consumers_no",
            "model",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return [
            "user",
            "avatar",
        ]


class AgentAdminDetailSerializer(AgentListSerializer):

    class Meta(AgentAdminListSerializer.Meta):
        fields = AgentAdminListSerializer.Meta.fields + [
            "context",
            "description",
        ]


class AgentMinSerializer(AgentListSerializer):
    
    avatar = ImageListSerializer()
    
    class Meta:
        model = Agent
        fields = ['id', 'name', 'avatar']