import json

from django.core.cache import cache
from django.db import models

from ..utils import Constants
from ..utils.Models import SmartModel
from ..utils.Fields import CharIDField

_SETTING_CACHE_TTL = 300


def _setting_cache_key(key: str) -> str:
    return f"setting:value:{key}"


def _json_list(raw, fallback: list) -> list:
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return list(fallback)
    if not isinstance(parsed, list):
        return list(fallback)
    return parsed


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
        Setting.get_or_create_refresh_onboarding_cadence_days()
        Setting.get_or_create_observations_enabled()
        Setting.get_or_create_observations_max_length()
        Setting.get_or_create_knowledge_min_confidence()
        Setting.get_or_create_history_max_turns()
        Setting.get_or_create_thin_answer_min_words()
        Setting.get_or_create_generic_answers_default()
        Setting.get_or_create_risk_keywords()
        Setting.get_or_create_trust_and_safety_email()
        Setting.get_or_create_ai_retrieval_enabled()
        Setting.get_or_create_ai_retrieval_exercise_enabled()
        Setting.get_or_create_store_turn_prompts()
        Setting.get_or_create_retrieval_min_similarity()
        Setting.get_or_create_retrieval_max_chunks()
        Setting.get_or_create_retrieval_max_tokens()
        Setting.get_or_create_retrieval_context_min_words()
        Setting.get_or_create_update_summary()
        Setting.get_or_create_update_exercise_summary()
        Setting.get_or_create_reply_length_instruction()
        Setting.get_or_create_one_question_instruction()
        Setting.get_or_create_returning_user_instruction()
        Setting.get_or_create_run_summary_prompt()
        Setting.get_or_create_run_summary_tone_guide()
        Setting.get_or_create_run_summary_max_length()

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
    def get_or_create_knowledge_min_confidence():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_KNOWLEDGE_MIN_CONFIDENCE,
            defaults={"value": str(Constants.KNOWLEDGE_MIN_CONFIDENCE)},
        )
        return setting

    @staticmethod
    def get_knowledge_min_confidence() -> float:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_KNOWLEDGE_MIN_CONFIDENCE,
            Setting.get_or_create_knowledge_min_confidence,
        )
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = Constants.KNOWLEDGE_MIN_CONFIDENCE
        return min(1.0, max(0.0, value))

    @staticmethod
    def get_or_create_history_max_turns():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_HISTORY_MAX_TURNS,
            defaults={"value": str(Constants.HISTORY_MAX_TURNS)},
        )
        return setting

    @staticmethod
    def get_history_max_turns() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_HISTORY_MAX_TURNS,
            Setting.get_or_create_history_max_turns,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.HISTORY_MAX_TURNS

    @staticmethod
    def get_or_create_session_inactivity_minutes():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_SESSION_INACTIVITY_MINUTES,
            defaults={"value": str(Constants.SESSION_INACTIVITY_MINUTES)},
        )
        return setting

    @staticmethod
    def get_session_inactivity_minutes() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_SESSION_INACTIVITY_MINUTES,
            Setting.get_or_create_session_inactivity_minutes,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.SESSION_INACTIVITY_MINUTES

    @staticmethod
    def get_or_create_authoring_test_idle_minutes():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_AUTHORING_TEST_IDLE_MINUTES,
            defaults={"value": str(Constants.AUTHORING_TEST_IDLE_MINUTES)},
        )
        return setting

    @staticmethod
    def get_authoring_test_idle_minutes() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_AUTHORING_TEST_IDLE_MINUTES,
            Setting.get_or_create_authoring_test_idle_minutes,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.AUTHORING_TEST_IDLE_MINUTES

    @staticmethod
    def get_or_create_thin_answer_min_words():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_THIN_ANSWER_MIN_WORDS,
            defaults={"value": str(Constants.THIN_ANSWER_MIN_WORDS)},
        )
        return setting

    @staticmethod
    def get_thin_answer_min_words() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_THIN_ANSWER_MIN_WORDS,
            Setting.get_or_create_thin_answer_min_words,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.THIN_ANSWER_MIN_WORDS

    @staticmethod
    def get_or_create_generic_answers_default():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_GENERIC_ANSWERS_DEFAULT,
            defaults={"value": json.dumps(Constants.DEFAULT_GENERIC_ANSWERS)},
        )
        return setting

    @staticmethod
    def get_generic_answers_default() -> list:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_GENERIC_ANSWERS_DEFAULT,
            Setting.get_or_create_generic_answers_default,
        )
        return _json_list(raw, Constants.DEFAULT_GENERIC_ANSWERS)

    @staticmethod
    def get_or_create_risk_keywords():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RISK_KEYWORDS,
            defaults={"value": json.dumps(Constants.DEFAULT_RISK_KEYWORDS)},
        )
        return setting

    @staticmethod
    def get_risk_keywords() -> dict:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RISK_KEYWORDS,
            Setting.get_or_create_risk_keywords,
        )
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return dict(Constants.DEFAULT_RISK_KEYWORDS)
        if not isinstance(parsed, dict):
            return dict(Constants.DEFAULT_RISK_KEYWORDS)
        return parsed

    @staticmethod
    def get_or_create_trust_and_safety_email():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_TRUST_AND_SAFETY_EMAIL,
            defaults={"value": ""},
        )
        return setting

    @staticmethod
    def get_trust_and_safety_email() -> str:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_TRUST_AND_SAFETY_EMAIL,
            Setting.get_or_create_trust_and_safety_email,
        )
        return (raw or "").strip()

    @staticmethod
    def get_or_create_ai_retrieval_enabled():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED,
            defaults={"value": "false"},
        )
        return setting

    @staticmethod
    def get_ai_retrieval_enabled() -> bool:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_AI_RETRIEVAL_ENABLED,
            Setting.get_or_create_ai_retrieval_enabled,
        )
        return str(raw).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def get_or_create_ai_retrieval_exercise_enabled():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_AI_RETRIEVAL_EXERCISE_ENABLED,
            defaults={"value": "false"},
        )
        return setting

    @staticmethod
    def get_ai_retrieval_exercise_enabled() -> bool:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_AI_RETRIEVAL_EXERCISE_ENABLED,
            Setting.get_or_create_ai_retrieval_exercise_enabled,
        )
        return str(raw).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def get_or_create_store_turn_prompts():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_STORE_TURN_PROMPTS,
            defaults={"value": "false"},
        )
        return setting

    @staticmethod
    def get_store_turn_prompts() -> bool:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_STORE_TURN_PROMPTS,
            Setting.get_or_create_store_turn_prompts,
        )
        return str(raw).strip().lower() in {"1", "true", "yes"}

    @staticmethod
    def get_or_create_retrieval_min_similarity():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RETRIEVAL_MIN_SIMILARITY,
            defaults={"value": str(Constants.RETRIEVAL_MIN_SIMILARITY_DEFAULT)},
        )
        return setting

    @staticmethod
    def get_retrieval_min_similarity() -> float:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RETRIEVAL_MIN_SIMILARITY,
            Setting.get_or_create_retrieval_min_similarity,
        )
        try:
            return float(raw)
        except (TypeError, ValueError):
            return Constants.RETRIEVAL_MIN_SIMILARITY_DEFAULT

    @staticmethod
    def get_or_create_retrieval_max_chunks():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RETRIEVAL_MAX_CHUNKS,
            defaults={"value": str(Constants.RETRIEVAL_MAX_CHUNKS_DEFAULT)},
        )
        return setting

    @staticmethod
    def get_retrieval_max_chunks() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RETRIEVAL_MAX_CHUNKS,
            Setting.get_or_create_retrieval_max_chunks,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.RETRIEVAL_MAX_CHUNKS_DEFAULT

    @staticmethod
    def get_or_create_retrieval_max_tokens():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RETRIEVAL_MAX_TOKENS,
            defaults={"value": str(Constants.RETRIEVAL_MAX_TOKENS_DEFAULT)},
        )
        return setting

    @staticmethod
    def get_retrieval_max_tokens() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RETRIEVAL_MAX_TOKENS,
            Setting.get_or_create_retrieval_max_tokens,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.RETRIEVAL_MAX_TOKENS_DEFAULT

    @staticmethod
    def get_or_create_retrieval_context_min_words():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RETRIEVAL_CONTEXT_MIN_WORDS,
            defaults={"value": str(Constants.RETRIEVAL_CONTEXT_MIN_WORDS_DEFAULT)},
        )
        return setting

    @staticmethod
    def get_retrieval_context_min_words() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RETRIEVAL_CONTEXT_MIN_WORDS,
            Setting.get_or_create_retrieval_context_min_words,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.RETRIEVAL_CONTEXT_MIN_WORDS_DEFAULT

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
    def get_or_create_update_summary():
        from ..utils.summary_prompts import DEFAULT_UPDATE_SUMMARY_PROMPT

        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_UPDATE_SUMMARY,
            defaults={"value": DEFAULT_UPDATE_SUMMARY_PROMPT},
        )
        return setting

    @staticmethod
    def get_update_summary() -> str:
        from ..utils.summary_prompts import DEFAULT_UPDATE_SUMMARY_PROMPT

        raw = Setting._cached_value(
            Constants.SETTING_KEY_UPDATE_SUMMARY,
            Setting.get_or_create_update_summary,
        )
        return (raw or "").strip() or DEFAULT_UPDATE_SUMMARY_PROMPT

    @staticmethod
    def get_or_create_update_exercise_summary():
        from ..utils.summary_prompts import DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT

        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_UPDATE_EXERCISE_SUMMARY,
            defaults={"value": DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT},
        )
        return setting

    @staticmethod
    def get_update_exercise_summary() -> str:
        from ..utils.summary_prompts import DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT

        raw = Setting._cached_value(
            Constants.SETTING_KEY_UPDATE_EXERCISE_SUMMARY,
            Setting.get_or_create_update_exercise_summary,
        )
        return (raw or "").strip() or DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT

    @staticmethod
    def get_or_create_reply_length_instruction():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_REPLY_LENGTH,
            defaults={"value": Constants.DEFAULT_REPLY_LENGTH_INSTRUCTION},
        )
        return setting

    @staticmethod
    def get_reply_length_instruction() -> str:
        """Stored reply-length line. Blank means the line is left out of the prompt."""
        raw = Setting._cached_value(
            Constants.SETTING_KEY_REPLY_LENGTH,
            Setting.get_or_create_reply_length_instruction,
        )
        return (raw or "").strip()

    @staticmethod
    def get_or_create_one_question_instruction():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_ONE_QUESTION,
            defaults={"value": Constants.DEFAULT_ONE_QUESTION_INSTRUCTION},
        )
        return setting

    @staticmethod
    def get_one_question_instruction() -> str:
        """Stored one-question line. Blank means the line is left out of the prompt."""
        raw = Setting._cached_value(
            Constants.SETTING_KEY_ONE_QUESTION,
            Setting.get_or_create_one_question_instruction,
        )
        return (raw or "").strip()

    @staticmethod
    def get_or_create_returning_user_instruction():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RETURNING_USER_INSTRUCTION,
            defaults={"value": Constants.DEFAULT_RETURNING_USER_INSTRUCTION},
        )
        return setting

    @staticmethod
    def get_returning_user_instruction() -> str:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RETURNING_USER_INSTRUCTION,
            Setting.get_or_create_returning_user_instruction,
        )
        return (raw or "").strip() or Constants.DEFAULT_RETURNING_USER_INSTRUCTION

    @staticmethod
    def get_or_create_run_summary_prompt():
        from ..utils.summary_prompts import DEFAULT_RUN_SUMMARY_PROMPT

        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RUN_SUMMARY_PROMPT,
            defaults={"value": DEFAULT_RUN_SUMMARY_PROMPT},
        )
        return setting

    @staticmethod
    def get_run_summary_prompt() -> str:
        from ..utils.summary_prompts import DEFAULT_RUN_SUMMARY_PROMPT

        raw = Setting._cached_value(
            Constants.SETTING_KEY_RUN_SUMMARY_PROMPT,
            Setting.get_or_create_run_summary_prompt,
        )
        return (raw or "").strip() or DEFAULT_RUN_SUMMARY_PROMPT

    @staticmethod
    def get_or_create_run_summary_tone_guide():
        from ..utils.summary_prompts import DEFAULT_RUN_SUMMARY_TONE_GUIDE

        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RUN_SUMMARY_TONE_GUIDE,
            defaults={"value": DEFAULT_RUN_SUMMARY_TONE_GUIDE},
        )
        return setting

    @staticmethod
    def get_run_summary_tone_guide() -> str:
        from ..utils.summary_prompts import DEFAULT_RUN_SUMMARY_TONE_GUIDE

        raw = Setting._cached_value(
            Constants.SETTING_KEY_RUN_SUMMARY_TONE_GUIDE,
            Setting.get_or_create_run_summary_tone_guide,
        )
        if raw is None:
            return DEFAULT_RUN_SUMMARY_TONE_GUIDE
        return str(raw).strip()

    @staticmethod
    def get_or_create_run_summary_max_length():
        setting, _ = Setting.objects.get_or_create(
            key=Constants.SETTING_KEY_RUN_SUMMARY_MAX_LENGTH,
            defaults={"value": str(Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH)},
        )
        return setting

    @staticmethod
    def get_run_summary_max_length() -> int:
        raw = Setting._cached_value(
            Constants.SETTING_KEY_RUN_SUMMARY_MAX_LENGTH,
            Setting.get_or_create_run_summary_max_length,
        )
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH

    @staticmethod
    def _cached_value(key: str, loader):
        cache_key = _setting_cache_key(key)
        value = cache.get(cache_key)
        if value is not None:
            return value
        value = loader().value
        cache.set(cache_key, value, _SETTING_CACHE_TTL)
        return value
