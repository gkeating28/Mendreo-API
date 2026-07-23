from rest_framework import serializers

from .models import Asset, Tag

from ..tag.serializers import TagListSerializer
from ..post.serializers import PostDetailSerializer
from ..file.serializers import FileDetailSerializer
from ..image.serializers import ImageDetailSerializer

from ..utils.Serializers import CreateModelSerializer, ListModelSerializer, EditModelSerializer


class AssetCreateSerializer(CreateModelSerializer):

    class Meta:
        model = Asset
        fields = [
            "tags",
            "post",
            "file",
            "image",
            "context",
        ]

    def validate(self, attrs):

        post = attrs.get("post", None)
        file = attrs.get("file", None)
        image = attrs.get("image", None)

        if (post and file) or (post and image) or (image and file):
            raise self.raise_validation_error(key="asset", error="Can only specify one of post, file or image")

        if not post and not file and not image:
            raise self.raise_validation_error(key="asset", error="Must specify one of post, file or image")

        return attrs


class AssetEditSerializer(EditModelSerializer):

    class Meta:
        model = Asset
        fields = [
            "tags",
            "post",
            "file",
            "image",
            "context",
        ]

    def validate(self, attrs):

        post = attrs.get("post", self.instance.post)
        file = attrs.get("file", self.instance.file)
        image = attrs.get("image", self.instance.image)

        if (post and file) or (post and image) or (image and file):
            raise self.raise_validation_error(key="asset", error="Can only specify one of post, file or image")

        return attrs


class AssetListSerializer(ListModelSerializer):

    post = PostDetailSerializer()
    file = FileDetailSerializer()
    image = ImageDetailSerializer()
    tags = TagListSerializer(many=True)

    class Meta:
        model = Asset
        fields = [
            "id",
            "tags",
            "post",
            "file",
            "image",
            "context",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def get_select_related_fields(cls):
        return [
            "file",
            "image",
            "post__file",
            "post__banner",
            "post__thumbnail",
        ]

    @classmethod
    def get_prefetch_related_fields(cls):
        return ["tags"]


class AssetDetailSerializer(AssetListSerializer):

    class Meta(AssetListSerializer.Meta):
        model = Asset
        fields = AssetListSerializer.Meta.fields + [
            'context',
        ]
