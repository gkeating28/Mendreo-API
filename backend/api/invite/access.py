from django.utils import timezone

from ..utils import Constants
from .models import InviteCode

EXPIRED_DETAIL = "This access code has expired."
REVOKED_DETAIL = "This access code is no longer active."


def _invite_code(user):
    if user is None or getattr(user, "type", None) != Constants.USER_TYPE_CONSUMER:
        return None

    consumer = getattr(user, "consumer", None)
    if consumer is None:
        return None

    try:
        return consumer.invite_code
    except InviteCode.DoesNotExist:
        return None


def invite_access_detail(user) -> str | None:
    """Why this invite account may not authenticate, or None.

    Inactive (revoked) wins over expiry so a revoked code is cut off even
    when it also has an expires_at. Accounts with no invite code are left
    alone.
    """
    code = _invite_code(user)
    if code is None:
        return None
    if not code.active:
        return REVOKED_DETAIL
    if code.expires_at is not None and timezone.now() >= code.expires_at:
        return EXPIRED_DETAIL
    return None
