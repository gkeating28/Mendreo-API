import json

from rest_framework import serializers

from .models import Setting
from ..utils import Constants
from ..utils.authoring import PROMPT_SETTING_FIELDS


class SettingCreateSerializer(serializers.Serializer):

    survey_enabled = serializers.BooleanField()
    general_prompt = serializers.CharField(required=False)
    therapeutic_prompt = serializers.CharField(required=False)
    refresh_onboarding_cadence_days = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS,
    )
    observations_enabled = serializers.BooleanField(
        required=False,
        default=Constants.DEFAULT_OBSERVATIONS_ENABLED,
    )
    observations_instruction = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_OBSERVATIONS_INSTRUCTION,
    )
    observations_tone_guide = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_OBSERVATIONS_TONE_GUIDE,
    )
    observations_max_length = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH,
    )
    insights_instruction = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_INSIGHTS_INSTRUCTION,
    )
    insights_tone_guide = serializers.CharField(
        required=False,
        allow_blank=True,
        default=Constants.DEFAULT_INSIGHTS_TONE_GUIDE,
    )
    insights_enabled = serializers.BooleanField(
        required=False,
        default=Constants.DEFAULT_INSIGHTS_ENABLED,
    )
    insights_pool_cap = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_POOL_CAP,
    )
    insights_shown_count = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_SHOWN_COUNT,
    )
    insights_recent_runs = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_RECENT_RUNS,
    )
    insights_min_pool_before_shuffle = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_MIN_POOL_BEFORE_SHUFFLE,
    )
    insights_max_length = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_MAX_LENGTH,
    )
    insights_batch_size = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_INSIGHTS_BATCH_SIZE,
    )
    knowledge_min_confidence = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1,
    )
    history_max_turns = serializers.IntegerField(required=False, min_value=1)
    session_inactivity_minutes = serializers.IntegerField(required=False, min_value=1)
    thin_answer_min_words = serializers.IntegerField(required=False, min_value=1)
    thin_answer_hint_enabled = serializers.BooleanField(required=False)
    require_exact_yes = serializers.BooleanField(required=False)
    ready_phrases = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=60),
        required=False,
        allow_empty=True,
        max_length=30,
    )
    finish_phrases = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=60),
        required=False,
        allow_empty=True,
        max_length=30,
    )
    generic_answers_default = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    chat_openers = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=120),
        required=False,
        allow_empty=True,
        max_length=20,
    )
    onboarding_copy_welcome = serializers.JSONField(required=False)
    onboarding_copy_initial = serializers.JSONField(required=False)
    onboarding_copy_return = serializers.JSONField(required=False)
    onboarding_copy_refresh = serializers.JSONField(required=False)
    risk_keywords = serializers.JSONField(required=False)
    high_risk_copy = serializers.JSONField(required=False)
    trust_and_safety_email = serializers.EmailField(required=False, allow_blank=True)
    store_turn_prompts = serializers.BooleanField(required=False)
    chat_debug_enabled = serializers.BooleanField(required=False)
    update_summary = serializers.CharField(required=False, allow_blank=True)
    update_exercise_summary = serializers.CharField(required=False, allow_blank=True)
    reply_length = serializers.CharField(required=False, allow_blank=True)
    one_question = serializers.CharField(required=False, allow_blank=True)
    client_knowledge_rule = serializers.CharField(required=False, allow_blank=True)
    onboarding_followup_permission_ask = serializers.CharField(required=False, allow_blank=True)
    onboarding_followup_decline = serializers.CharField(required=False, allow_blank=True)
    onboarding_followup_reask = serializers.CharField(required=False, allow_blank=True)
    onboarding_followup_chip_yes = serializers.CharField(required=False, allow_blank=True)
    onboarding_followup_chip_no = serializers.CharField(required=False, allow_blank=True)
    run_summary_prompt = serializers.CharField(required=False, allow_blank=True)
    run_summary_tone_guide = serializers.CharField(required=False, allow_blank=True)
    run_summary_max_length = serializers.IntegerField(
        required=False,
        min_value=1,
        default=Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH,
    )
    ai_retrieval_enabled = serializers.BooleanField(required=False)
    ai_retrieval_exercise_enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        incoming = set(getattr(self, "initial_data", {}) or {})
        if Constants.SETTING_KEY_AI_LAST_ANSWERER in incoming:
            raise serializers.ValidationError(
                {
                    Constants.SETTING_KEY_AI_LAST_ANSWERER: (
                        "This value is recorded by the server and cannot be edited."
                    )
                }
            )
        blocked = [name for name in PROMPT_SETTING_FIELDS if name in incoming]
        if blocked:
            raise serializers.ValidationError(
                {
                    name: "Save this text as a prompt version, not a setting."
                    for name in blocked
                }
            )
        pool_cap = self._insights_number(
            attrs, "insights_pool_cap", Setting.get_insights_pool_cap
        )
        shown_count = self._insights_number(
            attrs, "insights_shown_count", Setting.get_insights_shown_count
        )
        min_pool = self._insights_number(
            attrs,
            "insights_min_pool_before_shuffle",
            Setting.get_insights_min_pool_before_shuffle,
        )
        batch_size = self._insights_number(
            attrs, "insights_batch_size", Setting.get_insights_batch_size
        )
        errors = {}
        if pool_cap < shown_count:
            errors["insights_pool_cap"] = "Must be at least insights_shown_count."
        if min_pool < shown_count:
            errors["insights_min_pool_before_shuffle"] = (
                "Must be at least insights_shown_count."
            )
        if batch_size > pool_cap:
            errors["insights_batch_size"] = "Must be at most insights_pool_cap."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def _phrase_list(self, value):
        from ..utils.SessionStateMachine import ready_phrase_list_error

        error = ready_phrase_list_error(value)
        if error:
            raise serializers.ValidationError(error)
        return [phrase.strip() for phrase in value]

    def validate_ready_phrases(self, value):
        return self._phrase_list(value)

    def validate_finish_phrases(self, value):
        return self._phrase_list(value)

    def validate_chat_openers(self, value):
        seen = set()
        for text in value:
            if text in seen:
                raise serializers.ValidationError("Openers must be unique.")
            seen.add(text)
        return value

    def _validate_onboarding_copy(self, value):
        from ..onboarding.copy import validate_copy_payload

        return validate_copy_payload(value)

    def validate_onboarding_copy_welcome(self, value):
        return self._validate_onboarding_copy(value)

    def validate_onboarding_copy_initial(self, value):
        return self._validate_onboarding_copy(value)

    def validate_onboarding_copy_return(self, value):
        return self._validate_onboarding_copy(value)

    def validate_onboarding_copy_refresh(self, value):
        return self._validate_onboarding_copy(value)

    def validate_high_risk_copy(self, value):
        from ..utils.high_risk_copy import validate_high_risk_copy

        return validate_high_risk_copy(value)

    def _insights_number(self, attrs, name, getter):
        incoming = getattr(self, "initial_data", {}) or {}
        if name in incoming:
            return attrs[name]
        return getter()

    def create(self, validated_data):

        survey_setting = Setting.get_or_create_survey_enabled()
        survey_setting.value = str(validated_data.get("survey_enabled")).lower()
        survey_setting.save()

        cadence = Setting.get_or_create_refresh_onboarding_cadence_days()
        cadence.value = str(
            validated_data.get(
                "refresh_onboarding_cadence_days",
                Constants.DEFAULT_REFRESH_ONBOARDING_CADENCE_DAYS,
            )
        )
        cadence.save()

        obs_enabled = Setting.get_or_create_observations_enabled()
        obs_enabled.value = str(
            validated_data.get(
                "observations_enabled", Constants.DEFAULT_OBSERVATIONS_ENABLED
            )
        ).lower()
        obs_enabled.save()

        obs_max = Setting.get_or_create_observations_max_length()
        obs_max.value = str(
            validated_data.get(
                "observations_max_length", Constants.DEFAULT_OBSERVATIONS_MAX_LENGTH
            )
        )
        obs_max.save()

        incoming = getattr(self, "initial_data", {}) or {}
        if "insights_enabled" in incoming:
            insights_enabled = Setting.get_or_create_insights_enabled()
            insights_enabled.value = str(validated_data["insights_enabled"]).lower()
            insights_enabled.save()
        if "insights_pool_cap" in incoming:
            insights_pool_cap = Setting.get_or_create_insights_pool_cap()
            insights_pool_cap.value = str(validated_data["insights_pool_cap"])
            insights_pool_cap.save()
        if "insights_shown_count" in incoming:
            insights_shown_count = Setting.get_or_create_insights_shown_count()
            insights_shown_count.value = str(validated_data["insights_shown_count"])
            insights_shown_count.save()
        if "insights_recent_runs" in incoming:
            insights_recent_runs = Setting.get_or_create_insights_recent_runs()
            insights_recent_runs.value = str(validated_data["insights_recent_runs"])
            insights_recent_runs.save()
        if "insights_min_pool_before_shuffle" in incoming:
            insights_min_pool = Setting.get_or_create_insights_min_pool_before_shuffle()
            insights_min_pool.value = str(validated_data["insights_min_pool_before_shuffle"])
            insights_min_pool.save()
        if "insights_max_length" in incoming:
            insights_max_length = Setting.get_or_create_insights_max_length()
            insights_max_length.value = str(validated_data["insights_max_length"])
            insights_max_length.save()
        if "insights_batch_size" in incoming:
            insights_batch_size = Setting.get_or_create_insights_batch_size()
            insights_batch_size.value = str(validated_data["insights_batch_size"])
            insights_batch_size.save()

        if "knowledge_min_confidence" in validated_data:
            confidence = Setting.get_or_create_knowledge_min_confidence()
            confidence.value = str(validated_data["knowledge_min_confidence"])
            confidence.save()

        if "history_max_turns" in validated_data:
            turns = Setting.get_or_create_history_max_turns()
            turns.value = str(validated_data["history_max_turns"])
            turns.save()

        if "session_inactivity_minutes" in validated_data:
            idle = Setting.get_or_create_session_inactivity_minutes()
            idle.value = str(validated_data["session_inactivity_minutes"])
            idle.save()

        if "thin_answer_min_words" in validated_data:
            words = Setting.get_or_create_thin_answer_min_words()
            words.value = str(validated_data["thin_answer_min_words"])
            words.save()

        if "thin_answer_hint_enabled" in validated_data:
            hint = Setting.get_or_create_thin_answer_hint_enabled()
            hint.value = str(validated_data["thin_answer_hint_enabled"]).lower()
            hint.save()

        if "require_exact_yes" in validated_data:
            exact = Setting.get_or_create_require_exact_yes()
            exact.value = str(validated_data["require_exact_yes"]).lower()
            exact.save()

        if "ready_phrases" in validated_data:
            ready = Setting.get_or_create_ready_phrases()
            ready.value = json.dumps(validated_data["ready_phrases"])
            ready.save()

        if "finish_phrases" in validated_data:
            finish = Setting.get_or_create_finish_phrases()
            finish.value = json.dumps(validated_data["finish_phrases"])
            finish.save()

        if "generic_answers_default" in validated_data:
            generic = Setting.get_or_create_generic_answers_default()
            generic.value = json.dumps(validated_data["generic_answers_default"])
            generic.save()

        if "chat_openers" in validated_data:
            openers = Setting.get_or_create_chat_openers()
            openers.value = json.dumps(validated_data["chat_openers"])
            openers.save()

        if "risk_keywords" in validated_data:
            keywords = Setting.get_or_create_risk_keywords()
            keywords.value = json.dumps(validated_data["risk_keywords"])
            keywords.save()

        if "high_risk_copy" in validated_data:
            copy = Setting.get_or_create_high_risk_copy()
            copy.value = json.dumps(validated_data["high_risk_copy"])
            copy.save()

        if "trust_and_safety_email" in validated_data:
            address = Setting.get_or_create_trust_and_safety_email()
            address.value = validated_data["trust_and_safety_email"] or ""
            address.save()

        if "store_turn_prompts" in validated_data:
            capture = Setting.get_or_create_store_turn_prompts()
            capture.value = str(validated_data["store_turn_prompts"]).lower()
            capture.save()

        if "chat_debug_enabled" in validated_data:
            chat_debug = Setting.get_or_create_chat_debug_enabled()
            chat_debug.value = str(validated_data["chat_debug_enabled"]).lower()
            chat_debug.save()

        if "ai_retrieval_enabled" in validated_data:
            chat_retrieval = Setting.get_or_create_ai_retrieval_enabled()
            chat_retrieval.value = str(validated_data["ai_retrieval_enabled"]).lower()
            chat_retrieval.save()

        if "ai_retrieval_exercise_enabled" in validated_data:
            exercise_retrieval = Setting.get_or_create_ai_retrieval_exercise_enabled()
            exercise_retrieval.value = str(validated_data["ai_retrieval_exercise_enabled"]).lower()
            exercise_retrieval.save()

        if "update_summary" in incoming:
            summary_prompt = Setting.get_or_create_update_summary()
            summary_prompt.value = validated_data.get("update_summary") or ""
            summary_prompt.save()

        if "update_exercise_summary" in incoming:
            exercise_prompt = Setting.get_or_create_update_exercise_summary()
            exercise_prompt.value = validated_data.get("update_exercise_summary") or ""
            exercise_prompt.save()

        if "reply_length" in incoming:
            reply_length = Setting.get_or_create_reply_length_instruction()
            reply_length.value = validated_data.get("reply_length") or ""
            reply_length.save()

        if "one_question" in incoming:
            one_question = Setting.get_or_create_one_question_instruction()
            one_question.value = validated_data.get("one_question") or ""
            one_question.save()

        if "client_knowledge_rule" in incoming:
            rule = Setting.get_or_create_client_knowledge_rule()
            rule.value = validated_data.get("client_knowledge_rule") or ""
            rule.save()

        if "onboarding_followup_permission_ask" in incoming:
            permission_ask = Setting.get_or_create_onboarding_followup_permission_ask()
            permission_ask.value = validated_data.get("onboarding_followup_permission_ask") or ""
            permission_ask.save()

        if "onboarding_followup_decline" in incoming:
            decline = Setting.get_or_create_onboarding_followup_decline()
            decline.value = validated_data.get("onboarding_followup_decline") or ""
            decline.save()

        if "onboarding_followup_reask" in incoming:
            reask = Setting.get_or_create_onboarding_followup_reask()
            reask.value = validated_data.get("onboarding_followup_reask") or ""
            reask.save()

        if "onboarding_followup_chip_yes" in incoming:
            chip_yes = Setting.get_or_create_onboarding_followup_chip_yes()
            chip_yes.value = validated_data.get("onboarding_followup_chip_yes") or ""
            chip_yes.save()

        if "onboarding_followup_chip_no" in incoming:
            chip_no = Setting.get_or_create_onboarding_followup_chip_no()
            chip_no.value = validated_data.get("onboarding_followup_chip_no") or ""
            chip_no.save()

        if "run_summary_prompt" in incoming:
            run_prompt = Setting.get_or_create_run_summary_prompt()
            run_prompt.value = validated_data.get("run_summary_prompt") or ""
            run_prompt.save()

        if "run_summary_tone_guide" in incoming:
            run_tone = Setting.get_or_create_run_summary_tone_guide()
            run_tone.value = validated_data.get("run_summary_tone_guide") or ""
            run_tone.save()

        if "run_summary_max_length" in incoming:
            run_max = Setting.get_or_create_run_summary_max_length()
            run_max.value = str(
                validated_data.get(
                    "run_summary_max_length",
                    Constants.DEFAULT_RUN_SUMMARY_MAX_LENGTH,
                )
            )
            run_max.save()

        for key, variant in Constants.ONBOARDING_COPY_SETTING_KEYS.items():
            if key not in validated_data:
                continue
            row = Setting.get_or_create_onboarding_copy(variant)
            row.value = json.dumps(validated_data[key])
            row.save()

        return {
            "survey_enabled": validated_data.get("survey_enabled"),
            "refresh_onboarding_cadence_days": int(cadence.value),
            "observations_enabled": obs_enabled.value == "true",
            "observations_max_length": int(obs_max.value),
            "insights_enabled": Setting.get_insights_enabled(),
            "insights_pool_cap": Setting.get_insights_pool_cap(),
            "insights_shown_count": Setting.get_insights_shown_count(),
            "insights_recent_runs": Setting.get_insights_recent_runs(),
            "insights_min_pool_before_shuffle": Setting.get_insights_min_pool_before_shuffle(),
            "insights_max_length": Setting.get_insights_max_length(),
            "insights_batch_size": Setting.get_insights_batch_size(),
            "knowledge_min_confidence": Setting.get_knowledge_min_confidence(),
            "history_max_turns": Setting.get_history_max_turns(),
            "session_inactivity_minutes": Setting.get_session_inactivity_minutes(),
            "thin_answer_min_words": Setting.get_thin_answer_min_words(),
            "thin_answer_hint_enabled": Setting.get_thin_answer_hint_enabled(),
            "require_exact_yes": Setting.get_require_exact_yes(),
            "ready_phrases": Setting.get_ready_phrases(),
            "finish_phrases": Setting.get_finish_phrases(),
            "generic_answers_default": Setting.get_generic_answers_default(),
            "chat_openers": Setting.get_chat_openers(),
            "risk_keywords": Setting.get_risk_keywords(),
            "high_risk_copy": Setting.get_high_risk_copy(),
            "trust_and_safety_email": Setting.get_trust_and_safety_email(),
            "store_turn_prompts": Setting.get_store_turn_prompts(),
            "chat_debug_enabled": Setting.get_chat_debug_enabled(),
            "ai_retrieval_enabled": Setting.get_ai_retrieval_enabled(),
            "ai_retrieval_exercise_enabled": Setting.get_ai_retrieval_exercise_enabled(),
            "update_summary": Setting.get_update_summary(),
            "update_exercise_summary": Setting.get_update_exercise_summary(),
            "reply_length": Setting.get_reply_length_instruction(),
            "one_question": Setting.get_one_question_instruction(),
            "client_knowledge_rule": Setting.get_client_knowledge_rule(),
            "onboarding_followup_permission_ask": Setting.get_onboarding_followup_permission_ask(),
            "onboarding_followup_decline": Setting.get_onboarding_followup_decline(),
            "onboarding_followup_reask": Setting.get_onboarding_followup_reask(),
            "onboarding_followup_chip_yes": Setting.get_onboarding_followup_chip_yes(),
            "onboarding_followup_chip_no": Setting.get_onboarding_followup_chip_no(),
            "run_summary_prompt": Setting.get_run_summary_prompt(),
            "run_summary_tone_guide": Setting.get_run_summary_tone_guide(),
            "run_summary_max_length": Setting.get_run_summary_max_length(),
            Constants.SETTING_KEY_ONBOARDING_COPY_WELCOME: Setting.get_onboarding_copy(
                Constants.KNOWLEDGE_FLOW_WELCOME
            ),
            Constants.SETTING_KEY_ONBOARDING_COPY_INITIAL: Setting.get_onboarding_copy(
                Constants.KNOWLEDGE_FLOW_INITIAL
            ),
            Constants.SETTING_KEY_ONBOARDING_COPY_RETURN: Setting.get_onboarding_copy(
                Constants.KNOWLEDGE_FLOW_RETURN
            ),
            Constants.SETTING_KEY_ONBOARDING_COPY_REFRESH: Setting.get_onboarding_copy(
                Constants.KNOWLEDGE_FLOW_REFRESH
            ),
        }
