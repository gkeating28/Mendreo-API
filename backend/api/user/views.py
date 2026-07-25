from __future__ import unicode_literals

import datetime, requests

from rest_framework.response import Response
from rest_framework.authtoken.models import Token

from django.contrib.auth.models import update_last_login
from rest_framework import status

from django.contrib.auth.hashers import check_password, make_password
from rest_framework.views import APIView

from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User
from .serializers import UserDetailSerializer, password_validate

from ..admin.models import Admin
from ..admin.serializers import AdminDetailSerializer

from ..consumer.serializers import Consumer, ConsumerDetailSerializer

from rest_framework.exceptions import PermissionDenied


from ..utils import (
    Api,
    Token,
    Constants,
    DateUtils,
    QueryParams,
    Subscription as SubscriptionUtils
)

from ..utils.Permissions import IsAuthenticated

from ..utils.Views import SmartAPIView

from ..tasks import send_mail


class Login(SmartAPIView):

    permission_classes = []

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            return self.respond_with(
                "Invalid request, please provide an 'email' and 'password' field",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        invalid_credentials_response = self.respond_with(
            "A user with this email and password combination does not exist.",
            status_code=status.HTTP_400_BAD_REQUEST
        )

        try:
            user = User.objects.get(email__iexact=email)

            if not check_password(password, user.password):
                return invalid_credentials_response

            check_if_user_active(user)

            data = get_detailed(user)
            update_last_login(None, user)

            response = Response(data, status=status.HTTP_200_OK)

            token_data = Token.create(user)
            data[Constants.USER_AUTH_TOKENS] = token_data

            if not user.email_verified and can_send_verification_code(user):
                send_mail.delay_on_commit("send_account_verification_code", user.id)

            return response

        except User.DoesNotExist:
            return invalid_credentials_response


class Logout(SmartAPIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh", None)

        if not refresh_token:
            refresh_token = request.COOKIES.get(Constants.X_AUTH_REFRESH_TOKEN)

        if not refresh_token:
            return self.respond_with(
                "Please provide a refresh token",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        outstanding_token = OutstandingToken.objects.filter(
            token=refresh_token,
            user=request.user
        ).exclude(
            blacklistedtoken__token__token=refresh_token
        ).first()

        if not outstanding_token:
            return self.respond_with(
                "No refresh token found",
                status_code=status.HTTP_404_NOT_FOUND
            )

        try:
            BlacklistedToken.objects.create(token=outstanding_token)
        except Exception as e:
            return self.respond_with("Token is already expired", status_code=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


# refresh view in simple-jwt doesn't save token to outstanding table
# when refreshing token
# https://github.com/davesque/django-rest-framework-simplejwt/issues/25
class Refresh(SmartAPIView):

    permission_classes = []

    def post(self, request):
        refresh_token = request.data.get("refresh", None)
        if not refresh_token:
            refresh_token = request.COOKIES.get(Constants.X_AUTH_REFRESH_TOKEN)

        if not refresh_token:
            return self.respond_with("Please provide a refresh token",
                                     status_code=status.HTTP_400_BAD_REQUEST)

        outstanding_token = OutstandingToken.objects.filter(
            token=refresh_token
        ).exclude(
            blacklistedtoken__token__token=refresh_token
        ).first()

        if not outstanding_token:
            return self.respond_with("No refresh token found",
                                     status_code=status.HTTP_404_NOT_FOUND)

        if not outstanding_token.user:
            return self.respond_with("Invalid refresh token",
                                     status_code=status.HTTP_400_BAD_REQUEST)

        check_if_user_active(outstanding_token.user)

        try:
            BlacklistedToken.objects.create(token=outstanding_token)
        except Exception as e:
            return self.respond_with("Token is already expired", status_code=status.HTTP_400_BAD_REQUEST)

        token_data = Token.create(outstanding_token.user)

        return Response(token_data, status=status.HTTP_200_OK)


class RequestPasswordReset(SmartAPIView):

    permission_classes = []

    def post(self, request):

        if "email" not in request.data:
            return self.respond_with(
                "Please provide an email",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        email = request.data["email"]
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return self.respond_with(
                "This email does not belong to a valid user",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        check_if_user_active(user)

        if not can_send_verification_code(user):
            return Response(
                {"error": "Please wait 5 minutes between requests for a new code"},
                status=status.HTTP_400_BAD_REQUEST
            )

        send_mail.delay_on_commit("send_code", user.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ResetPassword(SmartAPIView):

    permission_classes = []

    def post(self, request):

        if "email" not in request.data or "password" not in request.data:
            return self.respond_with(
                "Please provide an email and password",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if "verification_code" not in request.data:
            return self.respond_with(
                "Please provide a verification code",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        email = request.data["email"]
        password = request.data["password"]
        verification_code = request.data["verification_code"]

        try:
            password_validate(password, False)
        except Exception as e:
            return self.respond_with(str(e), status_code=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return self.respond_with(
                "This email does not belong to a user",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        if user.verification_code != verification_code:
            return self.respond_with(
                "Invalid verification code",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        check_if_user_active(user)

        user.password = make_password(password)
        user.verification_code = None
        user.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class Info(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        check_if_user_active(user)

        user.last_seen = DateUtils.now()
        user.save()

        data = get_detailed(user)

        return Response(data, status=status.HTTP_200_OK)


class RequestVerifyEmail(SmartAPIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        check_if_user_active(user)

        if not can_send_verification_code(user):
            return Response(
                {"error": "Please wait 5 minutes between requests for a new code"},
                status=status.HTTP_400_BAD_REQUEST
            )

        send_mail.delay_on_commit("send_account_verification_code", user.id)

        return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyEmail(SmartAPIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        if "verification_code" not in request.data:
            return self.respond_with("Please provide a verification code",
                                     status_code=status.HTTP_400_BAD_REQUEST)

        verification_code = request.data["verification_code"]

        if not verification_code:
            return self.respond_with("Please provide a verification code",
                                     status_code=status.HTTP_400_BAD_REQUEST)

        user = request.user

        check_if_user_active(user)

        if user.verification_code != verification_code:
            return self.respond_with("Invalid verification code",
                                     status_code=status.HTTP_400_BAD_REQUEST)

        user.verification_code = None
        user.email_verified = True

        user.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


class FacebookCode(SmartAPIView):

    def get(self, request):
        access_token = QueryParams.get_str(request, "access_token")
        redirect_uri = QueryParams.get_str(request, "redirect_uri")
        long_lived = QueryParams.get_bool(request, "long_lived")

        if not access_token:
            return self.respond_with("Please provide an 'access_token'", status_code=status.HTTP_400_BAD_REQUEST)

        if not redirect_uri:
            return self.respond_with("Please provide a 'redirect_uri'", status_code=status.HTTP_400_BAD_REQUEST)

        if long_lived:
            access_token_response = requests.get("https://graph.facebook.com/oauth/access_token?", {
                "client_id": Api.FACEBOOK_CLIENT_ID,
                "client_secret": Api.FACEBOOK_CLIENT_SECRET_KEY,
                "grant_type": "fb_exchange_token",
                "fb_exchange_token": access_token
            }, timeout=15)
            access_token_response_json = access_token_response.json()
            access_token = access_token_response_json["access_token"]

        code_response = requests.get("https://graph.facebook.com/oauth/client_code?", {
            "client_id": Api.FACEBOOK_CLIENT_ID,
            "client_secret": Api.FACEBOOK_CLIENT_SECRET_KEY,
            "redirect_uri": redirect_uri,
            "access_token": access_token
        }, timeout=15)

        code_response_json = code_response.json()

        return Response(code_response_json, status=code_response.status_code)


def get_detailed(user):
    data = {}

    if user.type == Constants.USER_TYPE_ADMIN:
        admin = Admin.objects.get(user=user)
        admin_data = AdminDetailSerializer(admin).data
        data[Constants.USER_TYPE_ADMIN] = admin_data

    elif user.type == Constants.USER_TYPE_CONSUMER:
        consumer = Consumer.objects.get(user=user)

        subscription = consumer.subscription
        last_checked_at = subscription.last_checked_at
        threshold = DateUtils.now() - datetime.timedelta(hours=1)

        if not last_checked_at or last_checked_at < threshold:
            SubscriptionUtils.validate_subscription(consumer.subscription)

        consumer_data = ConsumerDetailSerializer(consumer).data
        data[Constants.USER_TYPE_CONSUMER] = consumer_data
    else:
        data["user"] = UserDetailSerializer(user).data

    return data


def check_if_user_active(user):
    if user.deleted_at is not None or user.status != Constants.USER_STATUS_ACTIVE:
        raise PermissionDenied("Your account is no longer active")


def can_send_verification_code(user):
    if not user.verification_code_sent_at:
        return True

    threshold = user.verification_code_sent_at + datetime.timedelta(minutes=5)
    return DateUtils.now() >= threshold
