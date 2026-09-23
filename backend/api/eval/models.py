from django.db import models

from ..utils import Constants
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel


class EvalCase(SmartModel):
    """Curated transcript and expected outcome for the evaluation harness."""

    id = CharIDField(primary_key=True, prefix="evlc_")

    name = models.CharField(max_length=255)
    kind = EnumField(options=Constants.EVAL_CASE_KINDS)
    source_session = models.ForeignKey(
        "api.Session",
        related_name="eval_cases",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    transcript = models.JSONField(null=True, blank=True)
    expected = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"EvalCase: {self.name}"


class EvalRun(SmartModel):
    """One execution of the active eval cases against a provider."""

    id = CharIDField(primary_key=True, prefix="evrn_")

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    prompt_versions = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=64, blank=True, default="")
    results = models.JSONField(default=dict, blank=True)
    passed = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"EvalRun: {self.id}"
