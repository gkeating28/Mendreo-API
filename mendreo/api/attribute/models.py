from __future__ import annotations

from django.db import models

from ..consumer.models import Consumer
from ..question.models import Question

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Attribute(SmartModel):
    """
    Model instance for storing answers by the consumers to questions created by platform admin
    """
    id = CharIDField(primary_key=True, prefix="attr_")

    consumer = models.ForeignKey(Consumer, related_name="attributes", on_delete=models.CASCADE)
    question = models.ForeignKey(Question, related_name="attributes", on_delete=models.CASCADE)

    key = models.CharField(null=True)
    value = models.TextField()

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Attribute: {}".format(self.id)
