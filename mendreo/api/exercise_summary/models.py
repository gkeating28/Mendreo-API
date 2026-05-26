from django.db import models

from ..consumer.models import Consumer
from ..exercise.models import Exercise

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class ExerciseSummary(SmartModel):

    id = CharIDField(primary_key=True, prefix="exsmry_")

    consumer = models.ForeignKey(Consumer, related_name="exercise_summaries", on_delete=models.CASCADE)

    exercise = models.ForeignKey(Exercise, related_name="exercise_summaries", on_delete=models.CASCADE)

    detailed = models.TextField(null=True)

    observations = models.TextField(null=True)

    next_steps = models.TextField(null=True)

    def update(self, date=None, freezer=None):
        from ..utils import Agent as AgentUtils

        AgentUtils.update_summary(self, date, freezer)

    @staticmethod
    def get_or_create(consumer: Consumer, exercise: Exercise):
        summary, _ = ExerciseSummary.objects.get_or_create(consumer=consumer, exercise=exercise)
        return summary
