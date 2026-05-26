from django.db import models

from ..consumer.models import Consumer
from ..price.models import Price

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Payment(SmartModel):
    id = CharIDField(primary_key=True, prefix="pay_")

    price = models.ForeignKey(Price, related_name="payments", on_delete=models.CASCADE)

    consumer = models.ForeignKey(Consumer, related_name="payments", on_delete=models.CASCADE)

    apple_receipt_id = models.TextField(null=True)
    google_receipt_id = models.TextField(null=True)

    apple_receipt_id_hash = models.CharField(null=True, db_index=True, unique=True)
    google_receipt_id_hash = models.CharField(null=True, db_index=True, unique=True)

    stripe_receipt_id = models.CharField(null=True, db_index=True, unique=True)
    stripe_subscription_id = models.CharField(null=True, db_index=True, unique=True)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Payment: {}".format(self.id)

    def save(self, *args, **kwargs):
        self.apple_receipt_id_hash = Payment.hash(self.apple_receipt_id)
        self.google_receipt_id_hash = Payment.hash(self.google_receipt_id)

        super().save(*args, **kwargs)

    @staticmethod
    def hash(val):
        import hashlib

        if not val:
            return None

        return hashlib.md5(val.encode()).hexdigest()
