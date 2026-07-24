from django.db import models

from ..utils import Constants
from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField


class Setting(SmartModel):

    id = CharIDField(primary_key=True, prefix="stng_")

    key = models.CharField(unique=True)
    value = models.TextField()

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Setting: {}"

    @staticmethod
    def create_all():
        Setting.get_or_create_survey_enabled()
        Setting.get_or_create_general_prompt()
        Setting.get_or_create_therapeutic_prompt()

    @staticmethod
    def get_or_create_survey_enabled():
        setting, created = Setting.objects.get_or_create(
            key="survey_enabled",
            defaults={
                "value": "true"
            }
        )
        return setting

    @staticmethod
    def get_survey_enabled():
        return Setting.get_or_create_survey_enabled().value == "true"

    @staticmethod
    def get_or_create_general_prompt():
        setting, created = Setting.objects.get_or_create(
            key="general_prompt",
            defaults={
                "value": Constants.PROMPT_GENERAL_GOALS
            }
        )

        return setting

    @staticmethod
    def get_general_prompt():
        return Setting.get_or_create_general_prompt().value

    @staticmethod
    def get_or_create_therapeutic_prompt():
        setting, created = Setting.objects.get_or_create(
            key="therapeutic_prompt",
            defaults={
                "value": Constants.PROMPT_THERAPEUTIC_INSTRUCTIONS
            }
        )
        return setting

    @staticmethod
    def get_therapeutic_prompt():
        return Setting.get_or_create_therapeutic_prompt().value
