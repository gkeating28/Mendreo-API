from django.utils import timezone

from ..utils.Constants import (
    CONSENT_ERROR_AGE,
    CONSENT_ERROR_LIMITATIONS,
    CONSENT_ERROR_VERSION,
    CONSENT_VERSION,
)
from .models import ConsumerConsent, ConsumerMarketingOptIn


def validate_consent_payload(data):
    """Return every reason the payload cannot be saved. Empty means it can."""
    errors = []
    if data.get("age_confirmed") is not True:
        errors.append(CONSENT_ERROR_AGE)
    if data.get("limitations_acknowledged") is not True:
        errors.append(CONSENT_ERROR_LIMITATIONS)
    if data.get("version") != CONSENT_VERSION:
        errors.append(CONSENT_ERROR_VERSION)
    return errors


def save_consent(consumer, data):
    """Record required consent and the separate marketing choice for this version.

    A repeat submission for the same version updates the existing rows.
    """
    now = timezone.now()
    opted_in = data.get("marketing_opt_in") is True
    ConsumerConsent.objects.update_or_create(
        consumer=consumer,
        version=CONSENT_VERSION,
        defaults={
            "age_confirmed": True,
            "age_confirmed_at": now,
            "limitations_acknowledged": True,
            "limitations_acknowledged_at": now,
        },
    )
    ConsumerMarketingOptIn.objects.update_or_create(
        consumer=consumer,
        version=CONSENT_VERSION,
        defaults={
            "opted_in": opted_in,
            "opted_in_at": now if opted_in else None,
        },
    )
    return opted_in
