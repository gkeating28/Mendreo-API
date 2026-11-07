from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from ..consumer.models import Consumer
from ..utils import Constants
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
    dismissed_at = models.DateTimeField(blank=True, null=True)

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


class UserInsight(SmartModel):
    """One conversation starter in a consumer's insight pool."""

    id = CharIDField(primary_key=True, prefix="uins_")

    consumer = models.ForeignKey(
        Consumer,
        related_name="insights",
        on_delete=models.CASCADE,
    )
    text = models.TextField()
    topic_key = models.CharField(max_length=255)
    source_run = models.ForeignKey(
        "api.Session",
        related_name="sourced_insights",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    generated_at = models.DateTimeField()
    last_shown_at = models.DateTimeField(blank=True, null=True)
    show_count = models.PositiveIntegerField(default=0)
    in_hand = models.BooleanField(default=False)
    retired_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["consumer", "generated_at"], name="api_uins_cons_gen_idx"),
            models.Index(fields=["consumer", "last_shown_at"], name="api_uins_cons_shown_idx"),
            models.Index(fields=["consumer", "in_hand"], name="api_uins_cons_hand_idx"),
        ]

    def __str__(self):
        return f"UserInsight: {self.id}"

    def get_permission_key(self):
        return "sessions"


class UserInsightCursor(SmartModel):
    """Last source fingerprint checked for a consumer. One row per consumer."""

    id = CharIDField(primary_key=True, prefix="uicur_")

    consumer = models.OneToOneField(
        Consumer,
        related_name="insight_cursor",
        on_delete=models.CASCADE,
    )
    source_fingerprint = models.CharField(max_length=64)
    checked_at = models.DateTimeField()

    def __str__(self):
        return f"UserInsightCursor: {self.id}"

    def get_permission_key(self):
        return "sessions"


class ScaleSubmission(SmartModel):
    """
    One completed psychological scale for a consumer on a calendar day.

    Questions are hardcoded in code, not stored. A check-in writes two rows
    (anxiety + positive_emotion) for the same submitted_on date.
    """

    class ScaleType(models.TextChoices):
        ANXIETY = Constants.SCALE_TYPE_ANXIETY
        POSITIVE_EMOTION = Constants.SCALE_TYPE_POSITIVE_EMOTION

    id = CharIDField(primary_key=True, prefix="ssub_")

    consumer = models.ForeignKey(
        Consumer,
        related_name="scale_submissions",
        on_delete=models.CASCADE,
    )
    scale_type = models.CharField(max_length=32, choices=ScaleType.choices)
    total_score = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(Constants.SCALE_TOTAL_MIN),
            MaxValueValidator(Constants.SCALE_TOTAL_MAX),
        ],
    )
    # Ireland calendar day (Europe/Dublin), same TZ as Progress mood/heatmap.
    submitted_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["consumer", "scale_type", "submitted_on"],
                name="uniq_scale_submission_per_day",
            ),
        ]
        indexes = [
            models.Index(
                fields=["consumer", "submitted_on"],
                name="api_ssub_consumer_on_idx",
            ),
        ]

    def __str__(self):
        return f"ScaleSubmission: {self.id}"

    def get_permission_key(self):
        return "sessions"
