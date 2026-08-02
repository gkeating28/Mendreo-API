from django.db import models

from ..consumer.models import Consumer
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class UserObservation(SmartModel):
    """
    Server-generated Patterns observation for a consumer (Slice E).

    Current card content = latest non-deleted row. On generation failure,
    retain the prior successful row (do not insert an empty observation).
    """

    id = CharIDField(primary_key=True, prefix="uobs_")

    consumer = models.ForeignKey(
        Consumer,
        related_name="observations",
        on_delete=models.CASCADE,
    )
    text = models.TextField()
    topic_tag = models.CharField(max_length=255, blank=True, default="")
    generated_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["consumer", "-generated_at"]),
        ]

    def __str__(self):
        return f"UserObservation: {self.id}"

    def get_permission_key(self):
        return "sessions"

    @staticmethod
    def latest_for(consumer):
        return (
            UserObservation.objects.filter(consumer=consumer)
            .order_by("-generated_at")
            .first()
        )
