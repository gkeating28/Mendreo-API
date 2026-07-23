from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password

from .models import User

from ..utils import Constants

from ..utils.Serializers import (
    CreateModelSerializer,
    EditModelSerializer,
    ListModelSerializer,
)


from django.core import exceptions
from django.core.validators import validate_email
from django.contrib.auth import password_validation as validators


class UserCreateSerializer(CreateModelSerializer):
    first_name = serializers.CharField(allow_null=False, allow_blank=False)
    last_name = serializers.CharField(allow_null=False, allow_blank=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "password", 'phone_country_code', 'phone_number']

    def validate_type(self, type):
        if type not in Constants.USER_TYPES:
            error = "type must be one of {}".format(Constants.USER_TYPES)
            raise serializers.ValidationError(error)

        return type

    def validate_status(self, status):
        if status not in Constants.USER_STATUSES:
            error = "status must be one of {}".format(Constants.USER_STATUSES)
            raise serializers.ValidationError(error)

        return status

    def validate_email(self, email):
        return email_validation(email)

    def validate_password(self, password):
        return password_validate(password)

    def validate(self, attrs):
        phone_number = attrs.get("phone_number", None)
        phone_country_code = attrs.get("phone_country_code", None)

        if (phone_country_code is not None and phone_number is None) or (phone_country_code is None and phone_number is not None):
            self.raise_validation_error("User", "'phone_number' or 'phone_country_code' cannot be null if one of them is provided")

        return attrs

    def get_mandatory_fields(self):
        return []


class UserAdminCreateSerializer(UserCreateSerializer):

    def validate(self, attrs):
        attrs["type"] = Constants.USER_TYPE_ADMIN
        return super(UserAdminCreateSerializer, self).validate(attrs)


class UserConsumerCreateSerializer(UserCreateSerializer):

    def validate(self, attrs):
        attrs["type"] = Constants.USER_TYPE_CONSUMER
        return super(UserConsumerCreateSerializer, self).validate(attrs)


class UserConsumerSocialCreateSerializer(UserConsumerCreateSerializer):
    first_name = serializers.CharField(allow_null=True)
    last_name = serializers.CharField(allow_null=True)

    def validate(self, attrs):
        attrs["email_verified"] = True
        return super(UserConsumerCreateSerializer, self).validate(attrs)


class UserEditSerializer(EditModelSerializer):
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    current_password = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'password',
            'current_password',
            'phone_country_code',
            'phone_number',
        ]

    def validate_password(self, password):
        return password_validate(password)

    def validate_email(self, email):
        instance = self.parent.instance.user if self.parent else self.instance
        return email_validation(email, instance)

    def validate(self, attrs):
        phone_number = attrs.get("phone_number", None)
        phone_country_code = attrs.get("phone_country_code", None)

        if (phone_country_code is not None and phone_number is None) or (phone_country_code is None and phone_number is not None):
            self.raise_validation_error("User", "'phone_number' or 'phone_country_code' cannot be null")

        return attrs

    def update(self, instance, validated_data):
        if 'password' in validated_data and 'current_password' not in validated_data:
            raise serializers.ValidationError("Please include current_password in order to update your password")

        if 'password' in validated_data:
            current_password = validated_data.pop("current_password")
            if not check_password(current_password, instance.password):
                raise serializers.ValidationError("Invalid request, your old password is incorrect")

        return super(UserEditSerializer, self).update(instance, validated_data)


class UserAdminEditSerializer(UserEditSerializer):
    email = serializers.CharField(required=False)

    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'email',
            'password',
            'phone_country_code',
            'phone_number',
        ]

    def validate_email(self, email):
        if self.instance:
            return super(UserAdminEditSerializer, self).validate_email(email)

        return email

    def update(self, instance, validated_data):
        # remove need for current_password
        return super(UserEditSerializer, self).update(instance, validated_data)


class UserMinSerializer(ListModelSerializer):

    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'full_name']


class UserListSerializer(ListModelSerializer):

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'full_name',
            'type',
            'created_at',
        ]


class UserDetailSerializer(UserListSerializer):

    class Meta(UserListSerializer.Meta):
        model = User
        UserListSerializer.Meta.fields += [
            'email',
            'email_verified',
            'phone_country_code',
            'phone_number'
        ]


class UserAdminListSerializer(ListModelSerializer):

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'full_name',
            'type',
            'email',
            'email_verified',
            'phone_country_code',
            'phone_number',
            'last_seen',
            'status',
            'created_at',
            'updated_at',
        ]


class UserAdminDetailSerializer(UserAdminListSerializer):
    pass


def password_validate(password, raise_error_with_serializer=True):
    try:
        validators.validate_password(password=password, user=User)

    except exceptions.ValidationError as e:
        error = e.messages[0]

        if raise_error_with_serializer:
            raise serializers.ValidationError(error)
        else:
            raise Exception(error)

    return make_password(password)


def email_validation(email, instance=None):
    email = email.lower()
    if instance and instance.email == email:
        return email

    if User.objects.filter(email__iexact=email).exists():
        error = "A user with this email already exists."
        raise serializers.ValidationError(error)

    try:
        validate_email(email)
    except Exception as e:
        raise serializers.ValidationError(e)

    return email
