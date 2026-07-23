import jwt, os

from social_core.backends.oauth import BaseOAuth2
from social_core.utils import handle_http_errors

from ..utils import DateUtils
from django.conf import settings
from ..consumer.models import Consumer


class AppleOAuth2(BaseOAuth2):

    name = 'apple'
    ACCESS_TOKEN_URL = 'https://appleid.apple.com/auth/token'
    ACCESS_TOKEN_METHOD = 'POST'
    ID_KEY = 'id'

    APPLE_CLIENT_ID = settings.SOCIAL_AUTH_APPLE_CLIENT_ID

    @handle_http_errors
    def do_auth(self, access_token, *args, **kwargs):
        response = kwargs["response"]

        if "id_token" not in response:
            raise Exception("No 'id_token'")

        id_token = response["id_token"]

        decoded = jwt.decode(id_token, options={"verify_signature": False})

        response.update({
            'email': decoded.get('email', None),
            'id': decoded.get('sub', None)
        })

        kwargs.update({'response': response, 'backend': self})

        return self.strategy.authenticate(*args, **kwargs)

    def get_user_details(self, response):
        email = response.get('email', None)
        first_name = self.data.get("first_name", "Anon")
        last_name = self.data.get("last_name", "User")

        consumer = Consumer.objects.filter(user__email__iexact=email).first()

        if consumer:
            first_name = consumer.user.first_name
            last_name = consumer.user.last_name

        details = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name
        }

        print("User Details", details)

        return details

    def get_key_and_secret(self):
        algorithm = 'ES256'

        headers = {
            'kid': settings.SOCIAL_AUTH_APPLE_KEY_ID,
            'alg': algorithm
        }

        payload = {
            'iss': settings.SOCIAL_AUTH_APPLE_TEAM_ID,
            'iat': DateUtils.now(),
            'exp': DateUtils.days_later(day_count=180),
            'aud': 'https://appleid.apple.com',
            'sub': self.APPLE_CLIENT_ID,
        }

        key_secret = settings.SOCIAL_AUTH_APPLE_KEY_SECRET

        client_secret = jwt.encode(
            payload,
            key_secret,
            algorithm=algorithm,
            headers=headers
        )

        return self.APPLE_CLIENT_ID, client_secret


class AppleWebOAuth2(AppleOAuth2):
    name = 'apple-web'
    APPLE_CLIENT_ID = os.environ.get("APPLE_SERVICES_ID", "")
