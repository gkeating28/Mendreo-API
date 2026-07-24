from django.db import models

from ..utils.Models import SmartModel

from ..utils.Fields import EnumField, CharIDField

from ..currency.models import Currency

from ..utils import Constants


class Price(SmartModel):

    id = CharIDField(primary_key=True, prefix="prc_")

    currency = models.ForeignKey(Currency, related_name="prices", on_delete=models.CASCADE)

    amount = models.PositiveIntegerField()

    frequency = EnumField(options=Constants.FREQUENCIES, default=None, null=True)

    apple_id = models.CharField(max_length=255, null=True)
    google_id = models.CharField(max_length=255, null=True)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Price: {}".format(self.amount)
