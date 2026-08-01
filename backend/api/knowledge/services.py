from __future__ import annotations

from pydantic import BaseModel, Field

from ..utils import Constants
from ..utils.AI import AI


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
    """
    type_hint = f" The field value type is '{value_type}'." if value_type else ""
    prompt = (
        f"{extraction_prompt.strip()}\n\n"
        f"User reply:\n{sample_reply.strip()}\n\n"
        f"Extract the knowledge value from the user reply.{type_hint} "
        f"Return a concise value and a confidence between 0 and 1."
    )
    return AI.ask(prompt, KnowledgeExtractionResult, temperature=0.1)


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

        KnowledgeEntry.objects.create(
            consumer=attribute.consumer,
            field=field,
            value=attribute.value,
            source=Constants.KNOWLEDGE_ENTRY_SOURCE_ONBOARDING,
            confidence=1.0,
            attribute=attribute,
        )
        created += 1

    return {"created": created, "skipped": skipped, "unmatched": unmatched}
