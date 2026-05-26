from django.db import models

from ..consumer.models import Consumer
from ..utils.Models import SmartModel


class Summary(SmartModel):

    consumer = models.OneToOneField(
        Consumer,
        on_delete=models.CASCADE,
        related_name="summary",
        primary_key=True
    )

    detailed = models.TextField(null=True)

    observations = models.TextField(null=True)

    next_steps = models.TextField(null=True)

    def update(self, freezer=None):
        from ..utils import Agent as AgentUtils

        AgentUtils.update_summary(self, None, freezer)

    @staticmethod
    def get_or_create(consumer: Consumer):
        summary, _ = Summary.objects.get_or_create(consumer=consumer)
        return summary
