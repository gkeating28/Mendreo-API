from .models import Post

from rest_framework import serializers

from ..user.serializers import UserMinSerializer
from ..file.serializers import FileListSerializer
from ..image.serializers import ImageListSerializer

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)

from ..utils import Constants


class PostCreateSerializer(CreateModelSerializer):

    type = serializers.ChoiceField(choices=Constants.POST_TYPES)

    class Meta:
        model = Post
        fields = [
            "body",
            "title",
            "banner",
            "type",
            "file",
            "status",
            "subtitle",
            "thumbnail",
            "created_by",
            "published_at",
        ]

    def validate_created_by(self, created_by):
        if created_by.type != Constants.USER_TYPE_ADMIN:
            self.raise_validation_error("created_by", "must be of type 'admin'")

        return created_by

    def validate(self, attrs):
        attrs = status_validation(self, attrs)
        attrs = field_validation(self, attrs)

        return attrs


class PostEditSerializer(EditModelSerializer):

    class Meta:
        model = Post
        fields = [
            "file",
            "body",
            "title",
            "banner",
            "status",
            "subtitle",
            "thumbnail",
            "published_at",
        ]

    def validate(self, attrs):

        attrs["type"] = self.instance.type
        attrs["file"] = self.instance.file

        attrs["body"] = attrs.get("body", self.instance.body)
        attrs["status"] = attrs.get("status", self.instance.status)
        attrs["published_at"] = attrs.get("published_at", self.instance.published_at)

        attrs = status_validation(self, attrs)
        attrs = field_validation(self, attrs)

        return attrs


class PostListSerializer(ListModelSerializer):

    banner = ImageListSerializer()
    thumbnail = ImageListSerializer()
    file = FileListSerializer()

    class Meta:
        model = Post
        fields = [
            "id",
            "file",
            "type",
            "body",
            "title",
            "banner",
            "subtitle",
            "thumbnail",
            "published_at",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return [
            "file",
            "banner",
            "thumbnail",
        ]


class PostDetailSerializer(PostListSerializer):
    pass


class PostAdminListSerializer(PostListSerializer):

    created_by = UserMinSerializer()

    class Meta(PostListSerializer.Meta):
        fields = PostListSerializer.Meta.fields + [
            "status",
            "created_by",
            "views_no",
            "impressions_no"
        ]

    @classmethod
    def get_select_related_fields(cls):
        return PostListSerializer.get_select_related_fields() + [
            "created_by",
        ]


class PostAdminDetailSerializer(PostAdminListSerializer):
    pass


def status_validation(serializer, attrs):

    status = attrs.get("status")
    published_at = attrs.get("published_at", None)

    if status == Constants.POST_STATUS_PUBLISHED:
        if not published_at:
            serializer.raise_validation_error(
                key="published_at", error=f"must be specified if status is '{Constants.POST_STATUS_PUBLISHED}'"
            )

    if status == Constants.POST_STATUS_GENERATING:
        serializer.raise_validation_error(
            key="status", error=f"invalid"
        )

    if serializer.instance and serializer.instance.status == Constants.POST_STATUS_GENERATING:
        serializer.raise_validation_error(
            key="status", error=f"Invalid, AI will replace the content of this post"
        )

    return attrs


def field_validation(serializer, attrs):

    type_ = attrs.get("type")
    body = attrs.get("body")
    file = attrs.get("file")

    if type_ == Constants.POST_TYPE_ARTICLE:
        if not body:
            serializer.raise_validation_error(
                key="body", error=f"This field is required."
            )

        if file:
            serializer.raise_validation_error(
                key="file", error=f"This field cannot be specified for type: '{type_}'."
            )

    if type_ in [Constants.POST_TYPE_VIDEO, Constants.POST_TYPE_PODCAST]:
        if not file:
            serializer.raise_validation_error(
                key="file", error=f"This field is required."
            )

    return attrs

