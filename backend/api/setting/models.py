from django.core.cache import cache
from django.db import models

from ..utils import Constants
from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField

_SETTING_CACHE_TTL = 300


def _setting_cache_key(key: str) -> str:
    return f"setting:value:{key}"


class Setting(SmartModel):

    id = CharIDField(primary_key=True, prefix="stng_")

    key = models.CharField(unique=True)
    value = models.TextField()

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Setting: {}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(_setting_cache_key(self.key))

    def delete(self):
        key = self.key
        super().delete()
        cache.delete(_setting_cache_key(key))

    @staticmethod
    def create_all():
        Setting.get_or_create_survey_enabled()
        Setting.get_or_create_general_prompt()
        Setting.get_or_create_therapeutic_prompt()
        Setting.get_or_create_refresh_onboarding_cadence_days()
        Setting.get_or_create_observations_enabled()
        Setting.get_or_create_observations_instruction()
        Setting.get_or_create_observations_tone_guide()
        Setting.get_or_create_observations_max_length()

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
        return Setting._cached_value("general_prompt", Setting.get_or_create_general_prompt)

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
        return Setting._cached_value("therapeutic_prompt", Setting.get_or_create_therapeutic_prompt)

    @staticmethod
    def get_or_create_refresh_onboarding_cadence_days():
        setting, _created = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_REFRESH_ONBOARDING_CADENCE_DAYS,
            defaults={
                "value": str(Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS),
            },
        )
        return setting

    @staticmethod
    def get_refresh_onboarding_cadence_days() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_REFRESH_ONBOARDING_CADENCE_DAYS,
            Setting.get_or_create_refresh_onboarding_cadence_days,
        )
        try:
            days = int(raw)
        except (TypeError, ValueError):
            days = Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS
        return max(1, days)

    @staticmethod
    def get_or_create_observations_enabled():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_OBSERVATIONS_ENABLED,
            defaults={"value": str(Constants.DEFAULT_OBSERVATIONS_ENABLED).lower()},
        )
        return setting

    @staticmethod
    def get_observations_enabled() -> bool:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_OBSERVATIONS_ENABLED,
            Setting.get_or_create_observations_enabled,
        )
        return str(raw).lower() == "true"

    @staticmethod
    def get_or_create_observations_instruction():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_OBSERVATIONS_INSTRUCTION,
            defaults={"value": Constants.DEFAULT_OBSERVATIONS_INSTRUCTION},
        )
        return setting

    @staticmethod
    def get_observations_instruction() -> str:
        return Setting._cached_value(
            Constants.SETTING_KEY_OBSERVATIONS_INSTRUCTION,
            Setting.get_or_create_observations_instruction,
        )

    @staticmethod
    def get_or_create_observations_tone_guide():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_OBSERVATIONS_TONE_GUIDE,
            defaults={"value": Constants.DEFAULT_OBSERVATIONS_TONE_GUIDE},
        )
        return setting

    @staticmethod
    def get_observations_tone_guide() -> str:
        return Setting._cached_value(
            Constants.SETTING_KEY_OBSERVATIONS_TONE_GUIDE,
            Setting.get_or_create_observations_tone_guide,
        )

    @staticmethod
    def get_or_create_observations_max_length():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_OBSERVATIONS_MAX_LENGTH,
            defaults={"value": str(Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH)},
        )
        return setting

    @staticmethod
    def get_observations_max_length() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_OBSERVATIONS_MAX_LENGTH,
            Setting.get_or_create_observations_max_length,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH

    @staticmethod
    def _cached_value(key: str, loader):
        cache_key = _setting_cache_key(key)
        value = cache.get(cache_key)
        if value is not None:
            return value
        value = loader().value
        cache.set(cache_key, value, _SETTING_CACHE_TTL)
        return value
