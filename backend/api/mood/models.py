from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from ..consumer.models import Consumer
from ..utils import Constants
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class MoodEntry(SmartModel):
    """
    Consumer mood check-in. Multiple entries per day are allowed.

    mood_score uses a fixed 1–5 scale:
      1 Low, 2 Flat, 3 Okay, 4 Good, 5 Great
    """

    id = CharIDField(primary_key=True, prefix="mood_")

    consumer = models.ForeignKey(
        Consumer,
        related_name="mood_entries",
        on_delete=models.CASCADE,
    )
    mood_score = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(Constants.MOOD_SCORE_MIN),
            MaxValueValidator(Constants.MOOD_SCORE_MAX),
        ],
    )
    note = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["consumer", "-created_at"]),
        ]
        verbose_name_plural = "mood entries"

    def __str__(self):
        return f"MoodEntry: {self.id}"

    @property
    def mood_label(self):
        return Constants.MOOD_SCORE_LABELS.get(self.mood_score, "")
