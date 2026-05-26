from rest_framework import serializers

from .models import File

from ..utils.Serializers import CreateModelSerializer, EditModelSerializer

from ..utils import File as FileUtils, Constants

import uuid
import os


class FileUploadSerializer(CreateModelSerializer):

    class Meta:
        model = File
        fields = ["name", "duration", "size", "created_by"]

    def validate(self, attrs):
        _, extension = os.path.splitext(attrs["name"])
        extension = extension.replace('.', '')

        if not extension:
            self.raise_validation_error("name", "name is missing extension")

        uid = uuid.uuid4()

        user = attrs.get("created_by")

        if user.type == Constants.USER_TYPE_CONSUMER:
            url = f"/consumers/{user.id}/files/{uid}.{extension}"
        elif user.type == Constants.USER_TYPE_ADMIN:
            url = f"/admins/{user.id}/files/{uid}.{extension}"
        else:
            self.raise_validation_error("created_by", "Not allowed to access this")

        attrs["url"] = url
        attrs["uploaded"] = False
        attrs["extension"] = extension

        return attrs


class FileEditSerializer(EditModelSerializer):
    uploaded = serializers.BooleanField(required=True)

    class Meta:
        model = File
        fields = ["uploaded"]

    def validate_uploaded(self, uploaded):
        if not uploaded:
            self.raise_validation_error("uploaded", "'uploaded' has to be true")

        return uploaded

    def validate(self, attrs):
        if not FileUtils.exists(self.instance.url.strip("/")):
            self.raise_validation_error("file", "file is not uploaded")

        attrs = {
            "uploaded": True,
            "token": None
        }

        return attrs


class FileListSerializer(serializers.ModelSerializer):

    url = serializers.SerializerMethodField()

    class Meta:
        model = File
        exclude = ["token", "uploaded"]

    def get_url(self, file):
        return file.get_url()


class FileDetailSerializer(serializers.ModelSerializer):

    url = serializers.SerializerMethodField()

    class Meta:
        model = File
        fields = '__all__'

    def get_url(self, file):
        return file.get_url()
