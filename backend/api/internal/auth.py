import hmac

from django.conf import settings
from rest_framework.exceptions import PermissionDenied


def require_internal_secret(request) -> None:
    provided = request.headers.get("X-Internal-Secret", "")
    expected = settings.INTERNAL_API_SECRET
    if not expected or not hmac.compare_digest(provided, expected):
        raise PermissionDenied("Invalid internal credentials")


def require_cron_secret(request) -> None:
    auth_header = request.headers.get("Authorization", "")
    expected = settings.CRON_SECRET
    if not expected or auth_header != f"Bearer {expected}":
        raise PermissionDenied("Invalid cron credentials")
