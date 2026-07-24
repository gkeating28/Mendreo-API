from django.db import models

from ..price.models import Price

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Package(SmartModel):

    id = CharIDField(primary_key=True, prefix="pkg_")

    title = models.CharField(max_length=255)

    price = models.ForeignKey(Price, related_name="packages", on_delete=models.CASCADE)

    default = models.BooleanField(default=False)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Package: {}".format(self.id)

    @staticmethod
    def get_default():
        return Package.objects.filter(
            price__amount=0,
            default=True
        ).first()
