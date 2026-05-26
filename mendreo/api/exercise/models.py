from __future__ import annotations

from django.db import models

from ..utils import Constants

from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField, EnumField


class Exercise(SmartModel):
    id = CharIDField(primary_key=True, prefix="exrcs_")

    title = models.CharField(max_length=255)
    subtitle = models.CharField(max_length=255)
    description = models.TextField()

    status = EnumField(options=Constants.EXERCISE_STATUSES, default=Constants.EXERCISE_STATUS_DRAFT)

    steps_no = models.PositiveIntegerField()

    icon = models.CharField(max_length=255)
    icon_svg = models.TextField(null=True)
    icon_background_color = models.CharField(max_length=255)

    completions_no = models.PositiveIntegerField(default=0)
    average_duration = models.PositiveIntegerField(default=300)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Exercise: {}".format(self.id)

    def get_permission_key(self):
        """Return the permission key for role-based access control"""
        return "exercises"
    
    def _update_average_duration(self):
        steps = self.steps.all()
        if steps.exists():
            total = sum(s.average_duration for s in steps)
            self.average_duration = total
        else:
            self.average_duration = 0
        self.save(update_fields=["average_duration"])
