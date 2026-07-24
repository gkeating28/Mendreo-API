from django.db import models

from ..price.models import Price

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Tag(SmartModel):

    id = CharIDField(primary_key=True, prefix="tag_")

    name = models.CharField(max_length=255)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Tag: {}".format(self.id)
