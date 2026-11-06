import secrets

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ..agent.models import Agent
from ..consumer.models import Consumer
from ..subscription.models import Subscription
from ..summary.models import Summary
from ..user.models import User
from ..utils import Constants
from ..utils.Subscription import grant_complimentary_access
from .models import InviteCode

# No 0/O or 1/I/L, so a code read aloud cannot be confused.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
INVITE_EMAIL_DOMAIN = "invite.mendreo.invalid"

INVALID_DETAIL = "That code isn't valid."
RATE_LIMIT_DETAIL = "Too many attempts. Try again in 15 minutes."

FAIL_LIMIT = 10
FAIL_WINDOW_SECONDS = 10 * 60
LOCK_WINDOW_SECONDS = 15 * 60

_IGNORED_IN_CODE = set(" \t\r\n-‐‑–—")


class RedeemRejected(Exception):
    def __init__(self, detail, status_code):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def normalize_code(raw) -> str:
    if not isinstance(raw, str):
        return ""
    return "".join(ch for ch in raw.strip().upper() if ch not in _IGNORED_IN_CODE)


def display_code(code: str) -> str:
    if len(code) != CODE_LENGTH:
        return code
    return f"{code[:4]}-{code[4:]}"


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.META.get("REMOTE_ADDR") or "unknown"


def _fail_key(ip: str) -> str:
    return f"invite_redeem_fail:{ip}"


def _lock_key(ip: str) -> str:
    return f"invite_redeem_lock:{ip}"


def is_locked(ip: str) -> bool:
    return cache.get(_lock_key(ip)) is not None


def record_failure(ip: str) -> bool:
    """Count a failed guess. True when this attempt should be answered with 429."""
    if is_locked(ip):
        return True

    key = _fail_key(ip)
    if cache.add(key, 1, FAIL_WINDOW_SECONDS):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, FAIL_WINDOW_SECONDS)
            count = 1

    if count > FAIL_LIMIT:
        cache.set(_lock_key(ip), 1, LOCK_WINDOW_SECONDS)
        return True
    return False


def is_expired(code: InviteCode, now=None) -> bool:
    if code.expires_at is None:
        return False
    return (now or timezone.now()) >= code.expires_at


def code_status(code: InviteCode, now=None) -> str:
    now = now or timezone.now()
    if not code.active:
        return "revoked"
    if is_expired(code, now):
        return "expired"
    if code.consumer_id or code.redeemed_at:
        return "redeemed"
    return "unused"


def account_name(code: InviteCode):
    consumer = code.consumer
    if consumer is None:
        return None
    user = consumer.user
    if user.full_name:
        return user.full_name
    if user.first_name:
        return user.first_name
    return None


def placeholder_email(code: InviteCode) -> str:
    return f"code-{code.id}@{INVITE_EMAIL_DOMAIN}"


def _generate_unique_code() -> str:
    for _ in range(20):
        candidate = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        if not InviteCode.objects.filter(code=candidate).exists():
            return candidate
    raise ValidationError("Could not generate a unique code. Try again.")


def create_codes(created_by, count: int, label_prefix: str, expires_at):
    prefix = (label_prefix or "").strip()
    created = []
    with transaction.atomic():
        for index in range(1, count + 1):
            label = f"{prefix} {index}".strip()
            created.append(
                InviteCode.objects.create(
                    code=_generate_unique_code(),
                    label=label,
                    expires_at=expires_at,
                    active=True,
                    created_by=created_by,
                )
            )
    return created


def _login_payload(user):
    from django.contrib.auth.models import update_last_login

    from ..user.views import check_if_user_active, get_detailed
    from ..utils import Token

    check_if_user_active(user)
    data = get_detailed(user)
    data[Constants.USER_AUTH_TOKENS] = Token.create(user)
    update_last_login(None, user)
    return data


def _create_account(code: InviteCode) -> User:
    agent = Agent.get_default()
    if agent is None:
        raise ValidationError("No default agent is configured.")

    user = User(
        email=placeholder_email(code),
        first_name="",
        last_name="",
        type=Constants.USER_TYPE_CONSUMER,
        email_verified=True,
        status=Constants.USER_STATUS_ACTIVE,
    )
    user.set_unusable_password()
    user.save()

    consumer = Consumer.objects.create(
        user=user,
        agent=agent,
        onboarded=False,
        date_of_birth=None,
        signup_source=Constants.SIGNUP_SOURCE_INVITE_CODE,
    )
    Summary.get_or_create(consumer)
    Subscription.create(consumer)
    grant_complimentary_access(consumer, mark_onboarded=False)

    code.consumer = consumer
    code.redeemed_at = timezone.now()
    code.save(update_fields=["consumer", "redeemed_at", "updated_at"])
    return user


def redeem(raw_code, request) -> dict:
    ip = client_ip(request)
    if is_locked(ip):
        raise RedeemRejected(RATE_LIMIT_DETAIL, 429)

    normalized = normalize_code(raw_code)
    with transaction.atomic():
        code = (
            InviteCode.objects.select_for_update()
            .filter(code=normalized)
            .first()
        )
        if code is None or not code.active or is_expired(code):
            locked = record_failure(ip)
            if locked:
                raise RedeemRejected(RATE_LIMIT_DETAIL, 429)
            raise RedeemRejected(INVALID_DETAIL, 400)

        if code.consumer_id:
            user = code.consumer.user
        else:
            user = _create_account(code)

    return _login_payload(user)


def reset_code(code: InviteCode) -> InviteCode:
    consumer = code.consumer
    if consumer is None:
        raise ValidationError("This code has not been redeemed.")

    if consumer.signup_source != Constants.SIGNUP_SOURCE_INVITE_CODE:
        raise ValidationError("This account was not created from an access code.")

    user = consumer.user
    with transaction.atomic():
        # The placeholder address is unique. Free it so the same code can
        # create a new account, and keep the old address non-routable.
        user.email = (
            f"code-{code.id}.deleted.{user.id}@{INVITE_EMAIL_DOMAIN}"
        )
        user.status = Constants.USER_STATUS_SUSPENDED
        user.deleted_at = timezone.now()
        user.save()

        code.consumer = None
        code.redeemed_at = None
        code.active = True
        code.save(update_fields=["consumer", "redeemed_at", "active", "updated_at"])
        consumer.delete()

    code.refresh_from_db()
    return code
