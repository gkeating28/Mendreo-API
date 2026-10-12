from ..utils.Constants import CONSENT_VERSION
from .models import ConsumerConsent


def has_current_consent(consumer):
    """True when this consumer has accepted the current required consent text."""
    if consumer is None:
        return False
    return ConsumerConsent.objects.filter(
        consumer=consumer,
        version=CONSENT_VERSION,
        age_confirmed=True,
        limitations_acknowledged=True,
    ).exists()
