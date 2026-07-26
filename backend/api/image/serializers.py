from rest_framework import serializers

from .models import Image

from ..utils import File, Constants, Api

from ..utils.Serializers import CreateModelSerializer, EditModelSerializer, ListModelSerializer, CreateSerializer

import uuid, os, shortuuid


class ImageUploadSerializer(CreateModelSerializer):
    name = serializers.CharField()
    width = serializers.IntegerField(min_value=1)
    height = serializers.IntegerField(min_value=1)

    class Meta:
        model = Image
        fields = ["created_by", "name", "width", "height", "size", 'blur_hash']

    def validate(self, attrs):
        name = attrs["name"]
        _, extension = os.path.splitext(name)
        extension = extension.replace('.', '')

        if not extension:
            self.raise_validation_error("name", "name is missing extension")

        if extension.lower() not in Constants.IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS:
            self.raise_validation_error("extension", f"extension needs to be one of {Constants.IMAGE_UPLOAD_ACCEPTABLE_EXTENSIONS}")

        user = attrs.get("created_by")
        path = self.get_path(user, extension)

        attrs["uploaded"] = False
        attrs["original"] = path
        attrs["token"] = shortuuid.uuid()
        attrs["extension"] = extension

        return attrs

    def get_path(self, user, extension):
        uid = uuid.uuid4()

        if user.type == Constants.USER_TYPE_CONSUMER:
            url = f"/consumers/{user.id}/images/{uid}.{extension}"
        else:
            url = f"/admins/{user.id}/images/{uid}.{extension}"

        return url


class ImageUploadEditSerializer(EditModelSerializer):
    uploaded = serializers.BooleanField(required=True)

    class Meta:
        model = Image
        fields = ["uploaded"]

    def validate_uploaded(self, uploaded):
        if not uploaded:
            self.raise_validation_error("uploaded", "'uploaded' has to be true")

        return uploaded

    def validate(self, attrs):
        if not File.exists(self.instance.original):
            self.raise_validation_error("image", "image is not uploaded")

        if self.instance.uploaded:
            self.raise_validation_error("image", "image set as uploaded already")

        attrs.update({
            "uploaded": True,
            "token": None,
        })

        return attrs


class ImageListSerializer(ListModelSerializer):

    thumbnail = serializers.SerializerMethodField()
    banner = serializers.SerializerMethodField()
    original = serializers.SerializerMethodField()

    resizer_url = serializers.SerializerMethodField()
    path = serializers.SerializerMethodField()

    class Meta:
        model = Image
        exclude = ["created_by"]

    def get_banner(self, image):
        return self.get_image_url(image, Constants.IMAGE_SIZE_TYPE_BANNER)

    def get_thumbnail(self, image):
        return self.get_image_url(image, Constants.IMAGE_SIZE_TYPE_THUMBNAIL)

    def get_original(self, image):
        return self.get_image_url(image, Constants.IMAGE_SIZE_TYPE_ORIGINAL)

    def get_image_url(self, image, size_type):
        if not image:
            return None

        original = image.original

        if original.startswith("http"):
            return original

        bucket_path = f"{Api.SUPABASE_STORAGE_BUCKET}{original}"

        if size_type == Constants.IMAGE_SIZE_TYPE_ORIGINAL:
            return f"{Api.SUPABASE_STORAGE_URL}/storage/v1/object/public/{bucket_path}"

        # Supabase's on-the-fly image transform endpoint (Pro plan and above:
        # https://supabase.com/docs/guides/storage/serving/image-transformations)
        # replaces CloudFront's path-based "/fit-in/WxH" resizer with query
        # params instead.
        size = Constants.IMAGE_SIZE_THUMBNAIL if size_type == Constants.IMAGE_SIZE_TYPE_THUMBNAIL else Constants.IMAGE_SIZE_BANNER
        width, height = size.split("x")
        return (
            f"{Api.SUPABASE_STORAGE_URL}/storage/v1/render/image/public/{bucket_path}"
            f"?width={width}&height={height}&resize=cover"
        )

    def get_resizer_url(self, image):
        if not image.uploaded:
            return None

        url = image.original

        ext = url.split(".")[-1].lower()
        if ext not in ["jpg", "jpeg", "png", "tiff", "webp", "svg"]:
            return None

        # NOTE: contract change from the old CloudFront resizer_url. Clients
        # used to build custom sizes as `{resizer_url}{WxH}{path}` (path
        # segment). Supabase's render endpoint takes width/height as query
        # params instead, so clients must now build:
        #   `{resizer_url}{path}?width=W&height=H&resize=cover|contain|fill`
        return f"{Api.SUPABASE_STORAGE_URL}/storage/v1/render/image/public/{Api.SUPABASE_STORAGE_BUCKET}"

    def get_path(self, image):
        if not image.uploaded:
            return None

        return image.original


class ImageDetailSerializer(ImageListSerializer):
    pass
