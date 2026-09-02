from django.db import models

from ..consumer.models import Consumer
from ..session.models import Session
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel

SUMMARY_STEP_ID = "summary"


class ExerciseReflection(SmartModel):
    """Private per-step (or whole-run) note on a completed exercise session."""

    id = CharIDField(primary_key=True, prefix="rflc_")

    session = models.ForeignKey(
        Session,
        related_name="reflections",
        on_delete=models.CASCADE,
    )
    consumer = models.ForeignKey(
        Consumer,
        related_name="exercise_reflections",
        on_delete=models.CASCADE,
    )
    step_id = models.CharField(max_length=64)
    text = models.TextField()

    class Meta:
        indexes = [
            models.Index(fields=["session", "step_id"]),
            models.Index(fields=["consumer", "-updated_at"]),
        ]

    def __str__(self):
        return f"ExerciseReflection: {self.id}"

    def get_permission_key(self):
        return "sessions"
