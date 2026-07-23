from rest_framework.test import APIClient
from rest_framework.response import Response

from ...utils import Data
from ....utils import Token

from ....user.models import User
from ....admin.models import Admin
from ....consumer.models import Consumer
from ....role.models import Role

import json, uuid

from .Request import get, post

client = APIClient()


def get_access_token(user: User) -> str:
    return "Bearer "+Token.create(user)["access"]
  

def get_platform_admin_access_token(admin: Admin = None):
    if not admin:
        admin = get_or_create_admin()

    return get_access_token(admin.user)


def get_consumer_access_token(consumer: Consumer = None):
    if not consumer:
        consumer = get_or_create_consumer()

    return get_access_token(consumer.user)


def login(email: str, password: str) -> Response:

    data = {
        "email": email,
        "password": password
    }

    response = post("/user/login", data)
    return response


def social_login(provider: str, object_response: bool = True) -> Consumer | Response:
    from unittest import mock

    if provider == "apple":
        with mock.patch("api.utils.AppleSignIn.AppleOAuth2.request_access_token") as mock_response:
            mock_response.return_value = {
                'access_token': 'Fake Access Toke',
                'token_type': 'Bearer',
                'expires_in': 3600,
                'refresh_token': 'Fake Refresh Token',
                'id_token': 'eyJraWQiOiJVYUlJRlkyZlc0IiwiYWxnIjoiUlMyNTYifQ.eyJpc3MiOiJodHRwczovL2FwcGxlaWQuYXBwbGUuY29tIiwiYXVkIjoiaWUubW9zYWljLm1lbmRyZW8uZGV2IiwiZXhwIjoxNzUzMDc5NzUzLCJpYXQiOjE3NTI5OTMzNTMsInN1YiI6IjAwMTIxMC5lYWM1Nzg5Mzc2ODM0NjcwOTZjZDk1MDMyNDk4NTE1Zi4wNDUzIiwibm9uY2UiOiI2YTRlMjgzMGQyMzllNjM3MGI5YWUxZjVlOGI1OThhOWQ2MGRhMTYyYmY4MDQ4OTQ3M2Q4MWY3NmUxZTY4ZWRkIiwiYXRfaGFzaCI6Im9tems1UGE4ZVcxbV9yU0lMX29yREEiLCJlbWFpbCI6IjY4cTdza3RjaDZAcHJpdmF0ZXJlbGF5LmFwcGxlaWQuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImlzX3ByaXZhdGVfZW1haWwiOnRydWUsImF1dGhfdGltZSI6MTc1Mjk5MzM1MSwibm9uY2Vfc3VwcG9ydGVkIjp0cnVlfQ.T3QN2AJtsuQiBwS1lxtdXOq8wzoq9EL3od7KwsGaR58MTHVvuXUFsEnZorL4vedam9qZUFxWVBhDqDKOyziR5pn7qE8nLPLk6BG8Sr6A75aDMgU_ryxgxGzyxG5qr4XWhNY4rDlK43f29nxwxMLa8JqIiEi1e8RgAFY3yrhgkH84nXqOSV-3SgXJjOJ8ozugcZLTM3jPTx5QuIQ1p237p-oV78_gDstNslRF3iwKLVv1GiYJRx7QiQDajdTZkzLF35sl5QsN9E983cmLljSyjPkRdZ7xPe5a0910VeBMyCD983VjPWo7-hbZ3ygdqJtDGGwvSoetHijVfeImtj1ZkQ'
            }

            data = Data.valid_social_auth_data(
                provider="apple",
                code="Fake Code"
            )

            response = post(endpoint="/user/login/social/jwt-pair-user/", data=data)
    elif provider == "google":
        with mock.patch("social_core.backends.google.GoogleOAuth2.request_access_token") as token_mock_response:
            with mock.patch("social_core.backends.google.GoogleOAuth2.user_data") as user_data_mock_response:
                token_mock_response.return_value = {
                    'access_token': 'Fake Access Token',
                    'expires_in': 3599,
                    'refresh_token': 'Fake Refresh Token',
                    'scope': 'https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile openid',
                    'token_type': 'Bearer',
                    'id_token': 'Fake Token Id'
                }
                user_data_mock_response.return_value = {
                    'sub': '123456',
                    'name': 'John Doe',
                    'given_name': 'John',
                    'family_name': 'Doe',
                    'picture': 'https://lh3.googleusercontent.com/a/ACg8ocJuhK5MneBwcRGUjE6FoJJlGrG8oooUYlyGUlPpCvz6KmGGzQ=s96-c',
                    'email': 'john.doe@gmail.com',
                    'email_verified': True,
                    'hd': 'gmail.com'
                }

                data = Data.valid_social_auth_data(
                    provider="google-oauth2",
                    code="Fake Code"
                )

                response = post(endpoint="/user/login/social/jwt-pair-user/", data=data)
    else:
        raise Exception(f"Unknown provider: {provider}")

    if not object_response:
        return response

    return Consumer.objects.get(user_id=response.json["consumer"]["user"]["id"])


def request_reset_password(email: str) -> Response:
    data = {"email": email}
    response = post("/user/request-reset-password", data)
    return response


def reset_password(email: str, verification_code: str, password: str) -> Response:
    data = {
        "email": email,
        "verification_code": verification_code,
        "password": password
    }

    response = post("/user/reset-password", data)

    return response


def logout(user: User, access_token: str = None, refresh_token: str = None) -> Response:
    if not access_token:
        tokens = Token.create(user)
        access_token = "Bearer "+tokens["access"]
        refresh_token = tokens["refresh"]

    data = {
        "refresh": refresh_token
    }

    response = post("/user/logout", data, access_token)

    return response


def user_info(access_token: str):
    response = get("/user/info", access_token)
    return response


def request_verify_email(access_token: str) -> Response:
    response = post("/user/request-verify-email", access_token=access_token)
    return response


def verify_email(access_token: str, code: str) -> Response:
    data = {
        "verification_code": code
    }

    response = post("/user/verify-email", data, access_token)

    return response


def get_or_create_admin() -> Admin:
    admin = Admin.objects.first()

    if not admin:
        admin = create_admin()

    return admin


def get_or_create_consumer() -> Consumer:
    consumer = Consumer.objects.first()

    if not consumer:
        consumer = create_consumer()

    return consumer


def get_oldest_admin() -> Admin:
    admin = Admin.objects.order_by("created_at").first()
    
    if not admin:
        admin = create_admin()
    return admin


def create_admin(email=None, data=None, object_response: bool = True) -> Admin | Response:
    from ....admin.serializers import AdminCreateSerializer

    if not data:
        data = Data.valid_admin_data()

    if email:
        data["user"]["email"] = email

    serializer = AdminCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    admin = serializer.save()

    admin.role = Role.get_super_admin()
    admin.save()

    if object_response:
        return admin

    login_data = {
        "email": data["user"]["email"],
        "password": data["user"]["password"]
    }

    return post(
        '/user/login',
        login_data,
    )


def create_consumer(email=None, data=None, object_response: bool = True) -> Consumer | Response:
    if not data:
        data = Data.valid_consumer_data()

    response = post(
        '/consumers',
        data,
    )

    if email:
        data["user"]["email"] = email

    if not object_response:
        return response

    return Consumer.objects.get(user_id=response.json["consumer"]["user"]["id"])
