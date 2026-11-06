from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class InviteAwareJWTAuthentication(JWTAuthentication):
    """Reject access tokens for an account whose invite code has expired.

    simplejwt otherwise trusts the token until it expires on its own.
    Refresh and password login are refused in check_if_user_active.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        from ..invite.access import invite_expired

        if invite_expired(user):
            raise AuthenticationFailed("This access code has expired.")
        return user
