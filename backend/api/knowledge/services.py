from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from ..utils import Constants


class KnowledgeExtractionResult(BaseModel):
    value: str = Field(description="Extracted knowledge value matching the field type")
    confidence: float = Field(description="Confidence score between 0 and 1", ge=0, le=1)


def mask_sensitive_value(value: str, sensitive: bool, obscure_pii: bool) -> str:
    """Return a restricted placeholder when the field is sensitive and PII is obscured."""
    if sensitive and obscure_pii:
        return Constants.KNOWLEDGE_RESTRICTED_PLACEHOLDER
    return value


def apply_sensitive_masking_to_entry_data(data, obscure_pii: bool):
    """
    Mask entry value(s) in serialized dict/list payloads when the related field is sensitive.
    Expects each entry dict to include either nested field.sensitive or top-level field_sensitive.
    """
    if isinstance(data, list):
        return [apply_sensitive_masking_to_entry_data(item, obscure_pii) for item in data]

    if not isinstance(data, dict):
        return data

    sensitive = False
    field = data.get("field")
    if isinstance(field, dict):
        sensitive = bool(field.get("sensitive"))
    elif data.get("field_sensitive") is not None:
        sensitive = bool(data.get("field_sensitive"))

    if "value" in data:
        data = {**data, "value": mask_sensitive_value(data["value"], sensitive, obscure_pii)}

    return data


def test_extraction(extraction_prompt: str, sample_reply: str, value_type: str | None = None) -> dict:
    """
    Dry-run extraction: send extraction prompt + sample reply to the model.
    Does not persist anything.

    AI is imported lazily so Vercel builds (which omit google-genai from
    requirements-vercel.txt) can still import knowledge URLs for migrate.
    """
    from ..utils.AI import AI

    type_hint = f" The field value type is '{value_type}'." if value_type else ""
    prompt = (
        f"{extraction_prompt.strip()}\n\n"
        f"User reply:\n{sample_reply.strip()}\n\n"
        f"Extract the knowledge value from the user reply.{type_hint} "
        f"Return a concise value and a confidence between 0 and 1."
    )
    return AI.ask(prompt, KnowledgeExtractionResult, temperature=0.1)


def invalidate_consumer_prompt_cache(consumer) -> None:
    """Clear cached session prompts so the next turn reloads knowledge."""
    from ..session.models import Session

    Session.objects.filter(consumer=consumer).exclude(cached_prompt__isnull=True).exclude(
        cached_prompt=""
    ).update(cached_prompt=None)


def write_knowledge_entry(
    *,
    consumer,
    field,
    value: str,
    source: str,
    confidence: float = 1.0,
    knowledge_question=None,
    session=None,
    attribute=None,
    created_by=None,
    invalidate_prompt_cache: bool = True,
):
    """
    Append a KnowledgeEntry for a consumer/field.

    Used by admin edits (source=admin), knowledge-question answers (source=question),
    AI inference (source=ai), and onboarding backfill (source=onboarding).
    """
    from .models import KnowledgeEntry

    if source not in Constants.KNOWLEDGE_ENTRY_SOURCES:
        raise ValueError(f"Invalid knowledge entry source: {source}")

    if confidence is None:
        confidence = 1.0
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")

    entry = KnowledgeEntry.objects.create(
        consumer=consumer,
        field=field,
        value=value,
        source=source,
        confidence=confidence,
        knowledge_question=knowledge_question,
        session=session,
        attribute=attribute,
        created_by=created_by,
    )

    if invalidate_prompt_cache:
        invalidate_consumer_prompt_cache(consumer)

    return entry


def get_current_entries(consumer, *, active_fields_only: bool = True):
    """
    Return the latest KnowledgeEntry per field for a consumer.

    Prefers a single query of recent entries, keeping the first (newest) per field.
    """
    from .models import KnowledgeEntry, KnowledgeField

    field_qs = KnowledgeField.objects.all()
    if active_fields_only:
        field_qs = field_qs.filter(active=True)

    fields = list(field_qs.order_by("category", "label"))
    if not fields:
        return []

    field_ids = [f.id for f in fields]
    entries = (
        KnowledgeEntry.objects.filter(consumer=consumer, field_id__in=field_ids)
        .select_related("field", "knowledge_question", "session", "created_by")
        .order_by("field_id", "-created_at")
    )

    current_by_field = {}
    for entry in entries:
        if entry.field_id not in current_by_field:
            current_by_field[entry.field_id] = entry

    return [current_by_field[f.id] for f in fields if f.id in current_by_field]


def get_knowledge_profile(consumer, *, obscure_pii: bool = False, active_fields_only: bool = True) -> dict:
    """
    Build the admin Knowledge tab payload: fields grouped by category with current values.
    """
    from .models import KnowledgeField

    field_qs = KnowledgeField.objects.all()
    if active_fields_only:
        field_qs = field_qs.filter(active=True)
    fields = list(field_qs.order_by("category", "label"))

    current = {e.field_id: e for e in get_current_entries(consumer, active_fields_only=active_fields_only)}

    grouped = defaultdict(list)
    for field in fields:
        entry = current.get(field.id)
        value = None
        source = None
        confidence = None
        updated_at = None
        entry_id = None
        restricted = False

        if entry:
            entry_id = entry.id
            source = entry.source
            confidence = entry.confidence
            updated_at = entry.created_at
            if field.sensitive and obscure_pii:
                value = Constants.KNOWLEDGE_RESTRICTED_PLACEHOLDER
                restricted = True
            else:
                value = entry.value

        grouped[field.category or "General"].append(
            {
                "field": {
                    "id": field.id,
                    "key": field.key,
                    "label": field.label,
                    "category": field.category,
                    "value_type": field.value_type,
                    "sensitive": field.sensitive,
                    "active": field.active,
                },
                "entry_id": entry_id,
                "value": value,
                "source": source,
                "confidence": confidence,
                "updated_at": updated_at,
                "restricted": restricted,
                "has_history": entry is not None,
            }
        )

    categories = [
        {"category": category, "fields": rows}
        for category, rows in grouped.items()
    ]
    # Keep stable ordering by first appearance (fields already category-ordered)
    return {
        "consumer_id": getattr(consumer, "pk", None) or getattr(consumer, "user_id", None),
        "categories": categories,
    }


def get_current_knowledge_summary(consumer, *, include_sensitive: bool = True) -> str:
    """
    Text summary of current knowledge for injection into the AI session prompt.
    """
    entries = get_current_entries(consumer, active_fields_only=True)
    if not entries:
        return "No structured knowledge recorded for this user yet."

    lines = ["Structured knowledge about this user:"]
    for entry in entries:
        field = entry.field
        if field.sensitive and not include_sensitive:
            continue
        lines.append(
            f"- {field.label} ({field.key}): {entry.value} "
            f"[source={entry.source}, confidence={entry.confidence:.2f}]"
        )

    if len(lines) == 1:
        return "No structured knowledge recorded for this user yet."

    return "\n".join(lines)


def get_activity_queryset(consumer, *, source: str | None = None):
    """Chronological KnowledgeEntry feed for a consumer (newest first)."""
    from .models import KnowledgeEntry

    qs = (
        KnowledgeEntry.objects.filter(consumer=consumer)
        .select_related("field", "knowledge_question", "session", "created_by")
        .order_by("-created_at")
    )
    if source:
        qs = qs.filter(source=source)
    return qs


def get_field_history_queryset(consumer, field):
    """History of entries for one field, newest first."""
    from .models import KnowledgeEntry

    return (
        KnowledgeEntry.objects.filter(consumer=consumer, field=field)
        .select_related("field", "knowledge_question", "session", "created_by")
        .order_by("-created_at")
    )


def backfill_knowledge_from_onboarding(consumer_id: str | None = None) -> dict:
    """
    Create KnowledgeEntry rows from existing onboarding Attribute answers.

    Matching is by Attribute.key / Question.attribute_key → KnowledgeField.key.
    Idempotent: skips attributes that already have a linked KnowledgeEntry.
    """
    from ..attribute.models import Attribute
    from ..question.models import Question
    from .models import KnowledgeEntry, KnowledgeField

    fields_by_key = {f.key: f for f in KnowledgeField.objects.filter(active=True)}
    if not fields_by_key:
        return {"created": 0, "skipped": 0, "unmatched": 0}

    onboarding_question_ids = Question.objects.filter(
        survey=False,
        exercise__isnull=True,
        session__isnull=True,
    ).values_list("id", flat=True)

    attributes = Attribute.objects.filter(question_id__in=onboarding_question_ids).select_related(
        "question", "consumer"
    )
    if consumer_id:
        attributes = attributes.filter(consumer_id=consumer_id)

    already_linked = set(
        KnowledgeEntry.objects.filter(attribute__isnull=False).values_list("attribute_id", flat=True)
    )

    created = 0
    skipped = 0
    unmatched = 0

    for attribute in attributes.iterator():
        if attribute.id in already_linked:
            skipped += 1
            continue

        key = attribute.key or (attribute.question.attribute_key if attribute.question_id else None)
        field = fields_by_key.get(key) if key else None
        if not field:
            unmatched += 1
            continue

        write_knowledge_entry(
            consumer=attribute.consumer,
            field=field,
            value=attribute.value,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
            confidence=1.0,
            attribute=attribute,
            invalidate_prompt_cache=False,
        )
        created += 1

    return {"created": created, "skipped": skipped, "unmatched": unmatched}
