from django.utils import timezone

from ..utils import Constants
from .models import InviteCode


def invite_expired(user) -> bool:
    """True when this user was created from a code that is now past expires_at."""
    if user is None or getattr(user, "type", None) != Constants.USER_TYPE_CONSUMER:
        return False

    consumer = getattr(user, "consumer", None)
    if consumer is None:
        return False

    try:
        code = consumer.invite_code
    except InviteCode.DoesNotExist:
        return False

    if code is None or code.expires_at is None:
        return False

    return timezone.now() >= code.expires_at
