"""V2 Onboarding / Return / Refresh flow services (Slice D)."""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from ..exercise.pre_exercise import resolve_template
from ..knowledge.models import KnowledgeEntry, KnowledgeQuestion
from ..knowledge.services import get_current_entries, write_knowledge_entry
from ..setting.models import Setting
from ..utils import Constants


def get_refresh_cadence_days() -> int:
    return Setting.get_refresh_onboarding_cadence_days()


def is_refresh_due(consumer) -> bool:
    """True when onboarded and cadence elapsed since last completed flow."""
    if not consumer.onboarded:
        return False
    cadence = get_refresh_cadence_days()
    last = consumer.last_onboarding_flow_completed_at
    if last is None:
        # Onboarded via legacy path with no V2 completion timestamp → due.
        return True
    return timezone.now() >= last + timedelta(days=cadence)


def recommend_variant(consumer) -> str:
    # Welcome is only in front of initial. An onboarded consumer keeps
    # return/refresh even when welcome_completed_at is null and welcome
    # questions exist. Restart clears onboarded, which opens welcome again.
    if not consumer.onboarded:
        if not welcome_is_complete(consumer):
            return Constants.KNOWLEDGE_FLOW_WELCOME
        return Constants.KNOWLEDGE_FLOW_INITIAL
    if is_refresh_due(consumer):
        return Constants.KNOWLEDGE_FLOW_REFRESH
    return Constants.KNOWLEDGE_FLOW_RETURN


def resolve_variant(consumer, requested: str | None = None) -> str:
    """
    Server-selected variant, or honor ?variant= when allowed.

    - Not onboarded, welcome not finished: welcome (other variants rejected)
    - Not onboarded, welcome finished: always initial (other variants rejected)
    - Onboarded: default return/refresh; an explicit variant is honored so
      replay/testing can load the initial knowledge flow again
    """
    if not consumer.onboarded and not welcome_is_complete(consumer):
        if requested and requested != Constants.KNOWLEDGE_FLOW_WELCOME:
            raise serializers.ValidationError({"variant": "Welcome is the next step."})
        return Constants.KNOWLEDGE_FLOW_WELCOME

    if not consumer.onboarded:
        if requested and requested != Constants.KNOWLEDGE_FLOW_INITIAL:
            raise serializers.ValidationError(
                {"variant": "Only the initial flow is available before onboarding is complete."}
            )
        return Constants.KNOWLEDGE_FLOW_INITIAL

    if requested:
        if requested not in Constants.KNOWLEDGE_FLOWS:
            raise serializers.ValidationError({"variant": f"Unknown variant '{requested}'."})
        return requested

    return recommend_variant(consumer)


def questions_for_variant(variant: str):
    qs = (
        KnowledgeQuestion.objects.filter(active=True, flows__contains=[variant])
        .select_related("target_field")
    )
    questions = list(qs)
    questions.sort(key=lambda q: (q.order_for_flow(variant), q.created_at))
    return questions


def welcome_answer_known(consumer, question) -> bool:
    """True when the welcome question's field already has a value.

    A current Knowledge Entry counts. Synced fields also count a non-empty
    account value (first or last name, or a date of birth).
    """
    field = question.target_field
    if field is None:
        return False
    entry = KnowledgeEntry.current_for(consumer, field)
    if entry is not None and str(entry.value or "").strip():
        return True
    sync = field.sync_to or Constants.KNOWLEDGE_SYNC_NONE
    user = getattr(consumer, "user", None)
    if sync == Constants.KNOWLEDGE_SYNC_FIRST_NAME:
        return bool(user and (user.first_name or "").strip())
    if sync == Constants.KNOWLEDGE_SYNC_LAST_NAME:
        return bool(user and (user.last_name or "").strip())
    if sync == Constants.KNOWLEDGE_SYNC_DATE_OF_BIRTH:
        return consumer.date_of_birth is not None
    return False


def visible_questions_for_variant(consumer, variant: str):
    questions = questions_for_variant(variant)
    if variant != Constants.KNOWLEDGE_FLOW_WELCOME:
        return questions
    return [question for question in questions if not welcome_answer_known(consumer, question)]


def welcome_is_complete(consumer) -> bool:
    if getattr(consumer, "welcome_completed_at", None):
        return True
    # None configured, or every welcome question is already known.
    return not visible_questions_for_variant(consumer, Constants.KNOWLEDGE_FLOW_WELCOME)


def build_token_context(consumer) -> dict[str, str]:
    context: dict[str, str] = {
        "user.first_name": getattr(consumer.user, "first_name", "") or "",
        "user.last_name": getattr(consumer.user, "last_name", "") or "",
    }

    last = consumer.last_onboarding_flow_completed_at
    if last:
        days = max(0, (timezone.now().date() - last.date()).days)
        context["days_since_last_flow"] = str(days)
        context["last_flow.completed_at"] = last.isoformat()
        context["last_flow.variant"] = consumer.last_onboarding_flow_variant or ""
    else:
        context["days_since_last_flow"] = ""
        context["last_flow.completed_at"] = ""
        context["last_flow.variant"] = ""

    for entry in get_current_entries(consumer, active_fields_only=True):
        context[f"knowledge.{entry.field.key}"] = entry.value or ""

    return context


def build_flow_payload(consumer, variant: str) -> dict:
    from .copy import resolved_flow_copy

    context = build_token_context(consumer)
    questions = visible_questions_for_variant(consumer, variant)
    serialized = []
    for question in questions:
        entry = KnowledgeEntry.current_for(consumer, question.target_field)
        chip_replies = question.chip_replies if isinstance(question.chip_replies, dict) else {}
        serialized.append(
            {
                "id": question.id,
                "prompt": resolve_template(question.prompt, context),
                "prompt_template": question.prompt,
                "response_type": question.response_type,
                "suggested_responses": question.suggested_responses or [],
                "chip_replies": chip_replies,
                "anchor_labels": question.anchor_labels,
                "value_labels": question.value_labels,
                "min_selections": question.min_selections,
                "max_selections": question.max_selections,
                "order": question.order_for_flow(variant),
                "target_field": {
                    "id": question.target_field_id,
                    "key": question.target_field.key,
                    "label": question.target_field.label,
                    "value_type": question.target_field.value_type,
                    "sensitive": question.target_field.sensitive,
                    "sync_to": question.target_field.sync_to or Constants.KNOWLEDGE_SYNC_NONE,
                },
                "prior_value": entry.value if entry else None,
            }
        )

    if variant == Constants.KNOWLEDGE_FLOW_INITIAL:
        closing_action = "enter_mendreo"
    elif variant == Constants.KNOWLEDGE_FLOW_WELCOME:
        closing_action = "continue"
    else:
        closing_action = "back_to_today"
    return {
        "variant": variant,
        "recommended_variant": recommend_variant(consumer),
        "questions": serialized,
        "questions_total": len(serialized),
        "closing_action": closing_action,
        "abandonable": variant
        not in (Constants.KNOWLEDGE_FLOW_INITIAL, Constants.KNOWLEDGE_FLOW_WELCOME),
        "companion_name": "Toni",
        "copy": resolved_flow_copy(variant, consumer),
    }


def build_status_payload(consumer) -> dict:
    cadence = get_refresh_cadence_days()
    refresh_due = is_refresh_due(consumer)
    next_step = recommend_variant(consumer)
    return {
        "onboarded": consumer.onboarded,
        "refresh_due": refresh_due,
        "recommended_variant": next_step,
        "next_step": next_step,
        "cadence_days": cadence,
        "last_completed_at": consumer.last_onboarding_flow_completed_at,
        "last_completed_variant": consumer.last_onboarding_flow_variant,
    }


def _parse_multi_values(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def validate_answer_value(question: KnowledgeQuestion, value) -> str:
    response_type = question.response_type
    suggested = question.suggested_responses or []

    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise serializers.ValidationError({"value": "This field is required."})

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER:
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError(
                {"value": "Slider value must be an integer."}
            )
        if number < Constants.SLIDER_MIN or number > Constants.SLIDER_MAX:
            raise serializers.ValidationError(
                {
                    "value": (
                        f"Must be between {Constants.SLIDER_MIN} and "
                        f"{Constants.SLIDER_MAX}."
                    )
                }
            )
        return str(number)

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE:
        text = str(value)
        if suggested and text not in suggested:
            raise serializers.ValidationError(
                {"value": f"'{text}' is not a valid option."}
            )
        return text

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE:
        values = _parse_multi_values(value)
        for item in values:
            if suggested and item not in suggested:
                raise serializers.ValidationError(
                    {"value": f"'{item}' is not a valid option."}
                )
        count = len(values)
        if question.min_selections is not None and count < question.min_selections:
            raise serializers.ValidationError(
                {
                    "value": (
                        f"Must select at least {question.min_selections} option(s)."
                    )
                }
            )
        if question.max_selections is not None and count > question.max_selections:
            raise serializers.ValidationError(
                {
                    "value": (
                        f"Must select at most {question.max_selections} option(s)."
                    )
                }
            )
        if count == 0:
            raise serializers.ValidationError({"value": "Select at least one option."})
        return ",".join(values)

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_DATE:
        text = str(value).strip()
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            raise serializers.ValidationError({"value": "Enter a date as YYYY-MM-DD."})
        if parsed.isoformat() != text:
            raise serializers.ValidationError({"value": "Enter a date as YYYY-MM-DD."})
        return text

    return str(value)


def _sync_account_value(consumer, field, value):
    sync = field.sync_to or Constants.KNOWLEDGE_SYNC_NONE
    text = str(value or "").strip()
    if not text or sync == Constants.KNOWLEDGE_SYNC_NONE:
        return
    if sync == Constants.KNOWLEDGE_SYNC_FIRST_NAME:
        consumer.user.first_name = text
        consumer.user.save(update_fields=["first_name"])
        return
    if sync == Constants.KNOWLEDGE_SYNC_LAST_NAME:
        consumer.user.last_name = text
        consumer.user.save(update_fields=["last_name"])
        return
    if sync == Constants.KNOWLEDGE_SYNC_DATE_OF_BIRTH:
        # Same 18+ rule for every variant. submit_flow_answers is atomic, so
        # a rejection rolls back the Knowledge Entry written earlier in this
        # request as well as this account update.
        from ..consumer.age import meets_minimum_age

        dob = date.fromisoformat(text[:10])
        if not meets_minimum_age(dob):
            raise serializers.ValidationError(
                {"detail": Constants.WELCOME_UNDERAGE_MESSAGE}
            )
        consumer.date_of_birth = dob
        consumer.save(update_fields=["date_of_birth", "updated_at"])


@transaction.atomic
def submit_flow_answers(
    consumer, *, variant: str, answers: list[dict], complete: bool, classify_vagueness: bool = True
):
    """
    Write Knowledge Entries (source=onboarding) for flow answers.

    Initial may accept incomplete step syncs (complete=False) for client persistence.
    Return/Refresh require complete=True (discardable — no server draft).
    Vague-answer flagging runs after this request: a Celery task (or, when
    Celery is eager, the first general-chat turn) asks Gemini so complete
    is not blocked on one LLM call per free-text answer.
    """
    variant = resolve_variant(consumer, variant)
    # Validate against every active question in the variant. The client
    # resends answers it already posted; skip-if-known hides those on the
    # next read, but they are still part of the variant and not an error.
    flow_questions = questions_for_variant(variant)
    by_id = {q.id: q for q in flow_questions}
    known_ids = set()
    if variant == Constants.KNOWLEDGE_FLOW_WELCOME:
        known_ids = {
            question.id
            for question in flow_questions
            if welcome_answer_known(consumer, question)
        }

    if variant not in (
        Constants.KNOWLEDGE_FLOW_INITIAL,
        Constants.KNOWLEDGE_FLOW_WELCOME,
    ) and not complete:
        raise serializers.ValidationError(
            {
                "complete": (
                    "Return and Refresh flows are discardable; submit with "
                    "complete=true and all answers in one request."
                )
            }
        )

    if not answers:
        raise serializers.ValidationError({"answers": "Provide at least one answer."})

    written = []
    # Known welcome answers already satisfy complete=true, whether or not
    # the client sends them again.
    answered_ids = set(known_ids)

    for index, raw in enumerate(answers):
        question_id = raw.get("knowledge_question_id") or raw.get("question_id")
        if not question_id or question_id not in by_id:
            raise serializers.ValidationError(
                {f"answers[{index}]": "Unknown knowledge_question_id for this variant."}
            )
        if question_id in known_ids:
            continue
        question = by_id[question_id]
        try:
            normalized = validate_answer_value(question, raw.get("value"))
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({f"answers[{index}]": exc.detail})

        needs_followup = False
        followup_prompt = ""
        from ..utils.turn_hint import entry_quality, generic_answers_for

        confidence, review_status = entry_quality(
            normalized,
            response_type=question.response_type,
            generic_answers=generic_answers_for(question),
        )

        entry = write_knowledge_entry(
            consumer=consumer,
            field=question.target_field,
            value=normalized,
            source=(
                Constants.KNOWLEDGE_ENTRY_SOURCE_WELCOME
                if variant == Constants.KNOWLEDGE_FLOW_WELCOME
                else Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING
            ),
            knowledge_question=question,
            confidence=confidence,
            review_status=review_status,
            needs_followup=needs_followup,
            followup_prompt=followup_prompt,
            invalidate_prompt_cache=False,
        )
        _sync_account_value(consumer, question.target_field, normalized)
        written.append(entry)
        answered_ids.add(question_id)

    if complete:
        missing = [q.id for q in flow_questions if q.id not in answered_ids]
        if missing:
            raise serializers.ValidationError(
                {
                    "answers": (
                        "All questions in this variant must be answered to complete "
                        f"the flow. Missing: {missing}"
                    )
                }
            )

        if variant == Constants.KNOWLEDGE_FLOW_WELCOME:
            consumer.welcome_completed_at = timezone.now()
            consumer.save(update_fields=["welcome_completed_at", "updated_at"])
        else:
            now = timezone.now()
            consumer.last_onboarding_flow_completed_at = now
            consumer.last_onboarding_flow_variant = variant
            update_fields = [
                "last_onboarding_flow_completed_at",
                "last_onboarding_flow_variant",
                "updated_at",
            ]
            if variant == Constants.KNOWLEDGE_FLOW_INITIAL and not consumer.onboarded:
                consumer.onboarded = True
                update_fields.append("onboarded")
            if variant == Constants.KNOWLEDGE_FLOW_INITIAL:
                consumer.onboarding_followup_classified_at = (
                    None if classify_vagueness else now
                )
                update_fields.append("onboarding_followup_classified_at")
            consumer.save(update_fields=update_fields)
            if variant == Constants.KNOWLEDGE_FLOW_INITIAL and classify_vagueness:
                from ..knowledge.followup import schedule_onboarding_followup_classification

                schedule_onboarding_followup_classification(consumer)

    from ..knowledge.services import invalidate_consumer_prompt_cache

    invalidate_consumer_prompt_cache(consumer)

    return {
        "variant": variant,
        "complete": complete,
        "entries_written": len(written),
        "entry_ids": [e.id for e in written],
        "entries": [
            {
                "id": entry.id,
                "field_id": entry.field_id,
                "field_key": entry.field.key if entry.field_id else None,
                "field_label": entry.field.label if entry.field_id else None,
                "knowledge_question_id": entry.knowledge_question_id,
                "value": entry.value,
                "source": entry.source,
                "needs_followup": entry.needs_followup,
                "followup_attempts": entry.followup_attempts,
                "followup_prompt": entry.followup_prompt,
                "created_at": entry.created_at,
            }
            for entry in written
        ],
        "status": build_status_payload(consumer),
        "closing_action": (
            "enter_mendreo"
            if variant == Constants.KNOWLEDGE_FLOW_INITIAL
            else "back_to_today"
        ),
    }


def placeholder_value_for(question: KnowledgeQuestion):
    """Deterministic skip-complete answers for local testing."""
    suggested = list(question.suggested_responses or [])
    response_type = question.response_type

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_DATE:
        return "2000-01-01"

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER:
        return (Constants.SLIDER_MIN + Constants.SLIDER_MAX) // 2

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_SINGLE_CHOICE:
        return suggested[0] if suggested else "test"

    if response_type == Constants.KNOWLEDGE_RESPONSE_TYPE_MULTIPLE_CHOICE:
        needed = question.min_selections or 1
        if suggested:
            return suggested[:needed]
        return ["test"] * needed

    return "test"


def complete_onboarding_with_placeholders(consumer):
    """
    Skip the conversational flow by writing valid placeholder answers
    for the recommended variant and marking it complete.
    """
    variant = recommend_variant(consumer)
    questions = questions_for_variant(variant)

    if not questions:
        now = timezone.now()
        update_fields = [
            "last_onboarding_flow_completed_at",
            "last_onboarding_flow_variant",
            "updated_at",
        ]
        consumer.last_onboarding_flow_completed_at = now
        consumer.last_onboarding_flow_variant = variant
        if variant == Constants.KNOWLEDGE_FLOW_INITIAL and not consumer.onboarded:
            consumer.onboarded = True
            update_fields.append("onboarded")
        if variant == Constants.KNOWLEDGE_FLOW_INITIAL:
            consumer.onboarding_followup_classified_at = now
            update_fields.append("onboarding_followup_classified_at")
        consumer.save(update_fields=update_fields)
        from ..knowledge.services import invalidate_consumer_prompt_cache

        invalidate_consumer_prompt_cache(consumer)
        return {
            "variant": variant,
            "complete": True,
            "entries_written": 0,
            "entry_ids": [],
            "status": build_status_payload(consumer),
            "closing_action": (
                "enter_mendreo"
                if variant == Constants.KNOWLEDGE_FLOW_INITIAL
                else "back_to_today"
            ),
        }

    answers = [
        {"knowledge_question_id": question.id, "value": placeholder_value_for(question)}
        for question in questions
    ]
    return submit_flow_answers(
        consumer,
        variant=variant,
        answers=answers,
        complete=True,
        classify_vagueness=False,
    )


def restart_onboarding(consumer):
    """
    Clear onboarding progress so welcome and the initial flow can be re-run.
    Soft-deletes Knowledge Entries whose source is welcome or onboarding.
    Chat, exercise, and admin entries are left in place.
    """
    from ..knowledge.services import invalidate_consumer_prompt_cache

    KnowledgeEntry.objects.filter(
        consumer=consumer,
        source__in=[
            Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
            Constants.KNOWLEDGE_ENTRY_SOURCE_WELCOME,
        ],
    ).delete()

    consumer.onboarded = False
    consumer.welcome_completed_at = None
    consumer.last_onboarding_flow_completed_at = None
    consumer.last_onboarding_flow_variant = None
    consumer.onboarding_followup_consumed_at = None
    consumer.onboarding_followup_session_id = None
    consumer.onboarding_followup_consent = None
    consumer.onboarding_followup_classified_at = None
    consumer.save(
        update_fields=[
            "onboarded",
            "welcome_completed_at",
            "last_onboarding_flow_completed_at",
            "last_onboarding_flow_variant",
            "onboarding_followup_consumed_at",
            "onboarding_followup_session_id",
            "onboarding_followup_consent",
            "onboarding_followup_classified_at",
            "updated_at",
        ]
    )
    invalidate_consumer_prompt_cache(consumer)
    return {
        "restarted": True,
        "status": build_status_payload(consumer),
    }
