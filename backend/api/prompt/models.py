from django.db import models

from ..user.models import User
from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class PromptVersion(SmartModel):
    """Versioned admin prompt. One active row per key."""

    id = CharIDField(primary_key=True, prefix="prmv_")

    key = models.CharField(max_length=64)
    body = models.TextField()
    version = models.PositiveIntegerField()
    active = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User,
        related_name="prompt_versions",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key", "version"],
                name="uniq_prompt_version_key",
            )
        ]

    def __str__(self):
        return f"PromptVersion: {self.key} v{self.version}"
