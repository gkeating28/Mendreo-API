from django.db import models
from django.contrib.postgres.fields import ArrayField
from ..role.models import Role
from ..utils.Models import SmartModel
from ..utils.Fields import EnumField
from ..utils import Constants


class Permissions(SmartModel):

    role = models.OneToOneField(Role, primary_key=True, related_name="permissions", on_delete=models.CASCADE)

    users = ArrayField(EnumField(options=Constants.USERS_PERMISSIONS), blank=True, default=list)
    sessions = ArrayField(EnumField(options=Constants.SESSIONS_PERMISSIONS), blank=True, default=list)
    signups = ArrayField(EnumField(options=Constants.SIGNUPS_PERMISSIONS), blank=True, default=list)
    feedback = ArrayField(EnumField(options=Constants.FEEDBACK_PERMISSIONS), blank=True, default=list)
    exercises = ArrayField(EnumField(options=Constants.EXERCISES_PERMISSIONS), blank=True, default=list)
    assets = ArrayField(EnumField(options=Constants.ASSETS_PERMISSIONS), blank=True, default=list)
    questions = ArrayField(EnumField(options=Constants.QUESTIONS_PERMISSIONS), blank=True, default=list)
    roles = ArrayField(EnumField(options=Constants.ROLES_PERMISSIONS), blank=True, default=list)
    pii = ArrayField(EnumField(options=Constants.PII_PERMISSIONS), blank=True, default=list)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Permissions: {}".format(self.role)
