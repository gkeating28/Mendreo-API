"""V2 Onboarding / Return / Refresh flow services (Slice D)."""

from __future__ import annotations

from datetime import timedelta

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
    if not consumer.onboarded:
        return Constants.KNOWLEDGE_FLOW_INITIAL
    if is_refresh_due(consumer):
        return Constants.KNOWLEDGE_FLOW_REFRESH
    return Constants.KNOWLEDGE_FLOW_RETURN


def resolve_variant(consumer, requested: str | None = None) -> str:
    """
    Server-selected variant, or honor ?variant= when allowed.

    - Not onboarded: always initial (other variants rejected)
    - Onboarded: default return/refresh; an explicit variant is honored so
      replay/testing can load the initial knowledge flow again
    """
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
    context = build_token_context(consumer)
    questions = questions_for_variant(variant)
    serialized = []
    for question in questions:
        entry = KnowledgeEntry.current_for(consumer, question.target_field)
        serialized.append(
            {
                "id": question.id,
                "prompt": resolve_template(question.prompt, context),
                "prompt_template": question.prompt,
                "response_type": question.response_type,
                "suggested_responses": question.suggested_responses or [],
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
                },
                "prior_value": entry.value if entry else None,
            }
        )

    closing_action = (
        "enter_mendreo"
        if variant == Constants.KNOWLEDGE_FLOW_INITIAL
        else "back_to_today"
    )
    return {
        "variant": variant,
        "recommended_variant": recommend_variant(consumer),
        "questions": serialized,
        "questions_total": len(serialized),
        "closing_action": closing_action,
        "abandonable": variant != Constants.KNOWLEDGE_FLOW_INITIAL,
        "companion_name": "Toni",
    }


def build_status_payload(consumer) -> dict:
    cadence = get_refresh_cadence_days()
    refresh_due = is_refresh_due(consumer)
    return {
        "onboarded": consumer.onboarded,
        "refresh_due": refresh_due,
        "recommended_variant": recommend_variant(consumer),
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

    return str(value)


@transaction.atomic
def submit_flow_answers(consumer, *, variant: str, answers: list[dict], complete: bool):
    """
    Write Knowledge Entries (source=question) for flow answers.

    Initial may accept incomplete step syncs (complete=False) for client persistence.
    Return/Refresh require complete=True (discardable — no server draft).
    """
    variant = resolve_variant(consumer, variant)
    flow_questions = questions_for_variant(variant)
    by_id = {q.id: q for q in flow_questions}

    if variant != Constants.KNOWLEDGE_FLOW_INITIAL and not complete:
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
    answered_ids = set()

    for index, raw in enumerate(answers):
        question_id = raw.get("knowledge_question_id") or raw.get("question_id")
        if not question_id or question_id not in by_id:
            raise serializers.ValidationError(
                {f"answers[{index}]": "Unknown knowledge_question_id for this variant."}
            )
        question = by_id[question_id]
        try:
            normalized = validate_answer_value(question, raw.get("value"))
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({f"answers[{index}]": exc.detail})

        entry = write_knowledge_entry(
            consumer=consumer,
            field=question.target_field,
            value=normalized,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_QUESTION,
            knowledge_question=question,
            confidence=1.0,
            invalidate_prompt_cache=False,
        )
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
        consumer.save(update_fields=update_fields)

    from ..knowledge.services import invalidate_consumer_prompt_cache

    invalidate_consumer_prompt_cache(consumer)

    return {
        "variant": variant,
        "complete": complete,
        "entries_written": len(written),
        "entry_ids": [e.id for e in written],
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
        consumer, variant=variant, answers=answers, complete=True
    )


def restart_onboarding(consumer):
    """
    Clear onboarding progress so the initial flow can be re-run with new values.
    Soft-deletes knowledge written during onboarding and legacy Attribute answers.
    """
    from ..attribute.models import Attribute
    from ..knowledge.services import invalidate_consumer_prompt_cache

    KnowledgeEntry.objects.filter(consumer=consumer).delete()
    Attribute.objects.filter(
        consumer=consumer,
        question__survey=False,
        question__exercise__isnull=True,
    ).delete()

    consumer.onboarded = False
    consumer.last_onboarding_flow_completed_at = None
    consumer.last_onboarding_flow_variant = None
    consumer.save(
        update_fields=[
            "onboarded",
            "last_onboarding_flow_completed_at",
            "last_onboarding_flow_variant",
            "updated_at",
        ]
    )
    invalidate_consumer_prompt_cache(consumer)
    return {
        "restarted": True,
        "status": build_status_payload(consumer),
    }
