from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class InviteAwareJWTAuthentication(JWTAuthentication):
    """Reject access tokens for a revoked or expired invite account.

    simplejwt otherwise trusts the token until it expires on its own.
    Refresh and password login are refused in check_if_user_active.
    Reactivating the code makes the same access token valid again.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        from ..invite.access import invite_access_detail

        detail = invite_access_detail(user)
        if detail:
            raise AuthenticationFailed(detail)
        return user
