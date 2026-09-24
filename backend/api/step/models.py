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

    completion_label = models.CharField(max_length=255)
    completion_prompt = models.TextField(null=True, blank=True)

    # Stable id for last-run tokens. Unique among live steps of one exercise.
    key = models.CharField(max_length=255, null=True, blank=True)
    reference_material = models.TextField(null=True, blank=True)
    result_field = models.ForeignKey(
        "api.KnowledgeField",
        related_name="result_steps",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    # Advisory "done when" text. Backfilled from completion_criteria.
    done_when = models.TextField(null=True, blank=True)

    order = models.PositiveIntegerField(default=0)
    average_duration = models.PositiveIntegerField(default=300)
    success_title = models.CharField(max_length=255, default="Well Done!")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exercise", "key"],
                condition=models.Q(deleted_at__isnull=True, key__isnull=False),
                name="uniq_step_key_per_exercise",
            )
        ]