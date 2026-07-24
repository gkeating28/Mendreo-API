from django.db import models

from ..tag.models import Tag
from ..exercise.models import Exercise

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Step(SmartModel):
    id = CharIDField(primary_key=True, prefix="step_")

    exercise = models.ForeignKey(Exercise, related_name="steps", on_delete=models.CASCADE)

    tags = models.ManyToManyField(Tag, related_name="steps", blank=True)

    title = models.CharField(max_length=255)

    description = models.TextField()
    instructions = models.TextField()

    completion_criteria = models.TextField()
    completion_label = models.CharField(max_length=255)
    completion_prompt = models.TextField()

    order = models.PositiveIntegerField(default=0)
    average_duration = models.PositiveIntegerField(default=300)
    success_title = models.CharField(max_length=255, default="Well Done!")