from django.db import models

from ..utils.Fields import CharIDField


class ConsumerConsent(models.Model):
    """Required account consent for one version of the consent text.

    Marketing opt-in is stored on ConsumerMarketingOptIn and is never read
    when deciding whether a consumer may use the product.
    """

    id = CharIDField(primary_key=True, prefix="cnst_")
    consumer = models.ForeignKey(
        "api.Consumer",
        related_name="consents",
        on_delete=models.CASCADE,
    )
    version = models.CharField(max_length=32)
    age_confirmed = models.BooleanField()
    age_confirmed_at = models.DateTimeField()
    limitations_acknowledged = models.BooleanField()
    limitations_acknowledged_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "version"],
                name="unique_consumer_consent_version",
            ),
        ]


class ConsumerMarketingOptIn(models.Model):
    """Optional wellbeing-email choice. Never grants or removes access."""

    id = CharIDField(primary_key=True, prefix="mkto_")
    consumer = models.ForeignKey(
        "api.Consumer",
        related_name="marketing_opt_ins",
        on_delete=models.CASCADE,
    )
    version = models.CharField(max_length=32)
    opted_in = models.BooleanField()
    opted_in_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "version"],
                name="unique_consumer_marketing_opt_in_version",
            ),
        ]
