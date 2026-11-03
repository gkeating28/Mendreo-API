"""Conversation-starter pool. Generation and the shown hand. No task, no endpoint."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

RESULT_DISABLED = "disabled"
RESULT_NO_SOURCES = "no_sources"
RESULT_UNCHANGED = "unchanged"
RESULT_FAILED = "failed"
RESULT_EMPTY = "empty"
RESULT_GENERATED = "generated"


@dataclass(frozen=True)
class RunSource:
    id: str
    title: str
    line: str
    bullets: tuple[str, ...]


@dataclass(frozen=True)
class InsightSources:
    knowledge: str
    runs: tuple[RunSource, ...]
    sensitive_values: tuple[str, ...]


@dataclass(frozen=True)
class Hand:
    items: tuple
    can_refresh: bool


def collect_sources(consumer) -> InsightSources:
    """Eligible knowledge, usable finished runs, and sensitive values to screen."""
    from ..knowledge.services import get_current_entries
    from ..run.services import completed_runs_queryset
    from ..setting.models import Setting
    from ..utils.prompt_blocks import _eligible_entries
    from ..utils.session_close import _run_summary_blocked

    knowledge_lines = []
    for entry in _eligible_entries(consumer, "general"):
        value = (entry.value or "").strip()
        if not value:
            continue
        knowledge_lines.append(f"{entry.field.label}: {value}")

    limit = Setting.get_insights_recent_runs()
    runs = []
    for session in completed_runs_queryset(consumer):
        if _run_summary_blocked(session):
            continue
        summary = _usable_summary(session.run_summary)
        if summary is None:
            continue
        title = ""
        if session.exercise_id and session.exercise is not None:
            title = session.exercise.title or ""
        runs.append(
            RunSource(
                id=str(session.id),
                title=title or "Exercise",
                line=summary[0],
                bullets=summary[1],
            )
        )
        if len(runs) >= limit:
            break

    sensitive = []
    for entry in get_current_entries(consumer, active_fields_only=True):
        if not entry.field.sensitive:
            continue
        value = (entry.value or "").strip()
        if value:
            sensitive.append(value)

    return InsightSources(
        knowledge="\n".join(knowledge_lines),
        runs=tuple(runs),
        sensitive_values=tuple(sensitive),
    )


def source_fingerprint(sources: InsightSources) -> str:
    """Stable hash of the knowledge text plus each usable run id and summary."""
    payload = {
        "knowledge": sources.knowledge,
        "runs": [
            {"id": run.id, "line": run.line, "bullets": list(run.bullets)}
            for run in sources.runs
        ],
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_prompt(sources: InsightSources, pool, instruction: str, tone: str, batch_size: int, max_words: int) -> str:
    """Instruction, fact rule, tone, and the knowledge, runs, and current pool."""
    from ..utils.user_grounding import USER_FACT_RULE

    run_blocks = []
    for run in sources.runs:
        lines = [f"Run id: {run.id}", f"Exercise: {run.title}"]
        if run.line:
            lines.append(run.line)
        lines.extend(f"- {bullet}" for bullet in run.bullets)
        run_blocks.append("\n".join(lines))

    pool_lines = []
    for item in pool:
        pool_lines.append(f"{item.topic_key}: {item.text}")

    return "\n".join(
        [
            (instruction or "").strip(),
            "",
            USER_FACT_RULE,
            "",
            f"Tone guide: {(tone or '').strip()}",
            f"Create up to {batch_size} insights, each at most {max_words} words.",
            "",
            "<KNOWLEDGE>",
            sources.knowledge or "(none)",
            "</KNOWLEDGE>",
            "",
            "<RECENT_RUNS>",
            "\n\n".join(run_blocks) or "(none)",
            "</RECENT_RUNS>",
            "",
            "<CURRENT_POOL>",
            "\n".join(pool_lines) or "(none)",
            "</CURRENT_POOL>",
        ]
    )


def generate_insights_for_consumer(consumer) -> str:
    """Fill the pool from the current sources. Returns a short result code."""
    from ..setting.models import Setting

    if not Setting.get_insights_enabled():
        logger.info("Insight generation %s for %s", RESULT_DISABLED, consumer.pk)
        return RESULT_DISABLED

    sources = collect_sources(consumer)
    if not sources.knowledge.strip() and not sources.runs:
        logger.info("Insight generation %s for %s", RESULT_NO_SOURCES, consumer.pk)
        return RESULT_NO_SOURCES

    fingerprint = source_fingerprint(sources)
    from .models import UserInsightCursor

    cursor = UserInsightCursor.objects.filter(consumer=consumer).first()
    if cursor is not None and cursor.source_fingerprint == fingerprint:
        logger.info("Insight generation %s for %s", RESULT_UNCHANGED, consumer.pk)
        return RESULT_UNCHANGED

    try:
        batch = _ask(consumer, sources)
    except Exception as exc:
        logger.warning(
            "Insight generation failed for %s (%s)",
            consumer.pk,
            type(exc).__name__,
        )
        return RESULT_FAILED

    if not batch:
        logger.info("Insight generation %s for %s", RESULT_EMPTY, consumer.pk)
        return RESULT_EMPTY

    _store_batch(consumer, sources, batch, fingerprint)
    logger.info("Insight generation %s for %s", RESULT_GENERATED, consumer.pk)
    return RESULT_GENERATED


def next_hand(consumer, force_rotate: bool = False) -> Hand:
    """The shown starters. A page load keeps the hand unless it is short or stale."""
    from ..setting.models import Setting

    from .models import UserInsight

    shown = Setting.get_insights_shown_count()
    minimum = Setting.get_insights_min_pool_before_shuffle()
    with transaction.atomic():
        active = list(
            UserInsight.objects.filter(consumer=consumer, retired_at__isnull=True)
            .select_related("source_run__exercise")
            .select_for_update(of=("self",))
            .order_by("generated_at", "id")
        )
        can_refresh = len(active) >= minimum
        current = [item for item in active if item.in_hand]
        current.sort(key=lambda item: (item.generated_at, item.id))
        if not current:
            chosen = _pick(active, shown, set())
            _stamp(chosen, active)
            return Hand(tuple(chosen), can_refresh)

        below = len(active) < minimum
        others = [item for item in active if not item.in_hand]
        short = len(current) < shown and bool(others)
        stamped_at = max(
            (item.last_shown_at for item in current if item.last_shown_at is not None),
            default=None,
        )
        newer = (
            not below
            and stamped_at is not None
            and any(
                (not item.in_hand) and item.generated_at > stamped_at
                for item in active
            )
        )
        if force_rotate and not below:
            chosen = _pick(active, shown, {item.id for item in current})
            _stamp(chosen, active)
            return Hand(tuple(chosen), can_refresh)
        if short or newer:
            chosen = _pick(active, shown, set())
            _stamp(chosen, active)
            return Hand(tuple(chosen), can_refresh)
        return Hand(tuple(_ordered(current)[:shown]), can_refresh)


def _usable_summary(summary) -> tuple[str, tuple[str, ...]] | None:
    if not isinstance(summary, dict):
        return None
    line = str(summary.get("line") or "").strip()
    raw_bullets = summary.get("bullets") or []
    bullets = []
    if isinstance(raw_bullets, list):
        for item in raw_bullets:
            text = str(item or "").strip()
            if text:
                bullets.append(text)
    if not line and not bullets:
        return None
    return line, tuple(bullets)


def _ask(consumer, sources: InsightSources) -> list[dict]:
    from pydantic import BaseModel

    from ..setting.models import Setting
    from ..utils.AI import AI
    from ..utils import Constants
    from ..utils.prompt_blocks import ensure_prompt_versions

    from .models import UserInsight

    prompts = ensure_prompt_versions()
    instruction = prompts[Constants.PROMPT_KEY_INSIGHTS_INSTRUCTION].body
    tone = prompts[Constants.PROMPT_KEY_INSIGHTS_TONE_GUIDE].body
    pool = list(
        UserInsight.objects.filter(consumer=consumer, retired_at__isnull=True).order_by(
            "generated_at", "id"
        )
    )
    prompt = build_prompt(
        sources,
        pool,
        instruction,
        tone,
        Setting.get_insights_batch_size(),
        Setting.get_insights_max_length(),
    )

    class InsightItem(BaseModel):
        text: str = ""
        topic_key: str = ""
        source_run_id: str | None = None

    class InsightBatch(BaseModel):
        insights: list[InsightItem]

    data = AI.ask(prompt, InsightBatch, temperature=0.4)
    raw = data.get("insights") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _store_batch(consumer, sources: InsightSources, batch: list[dict], fingerprint: str) -> None:
    from ..session.models import Session
    from ..setting.models import Setting

    from .models import UserInsight, UserInsightCursor

    max_words = Setting.get_insights_max_length()
    batch_size = Setting.get_insights_batch_size()
    allowed = {run.id for run in sources.runs}
    active = list(
        UserInsight.objects.filter(consumer=consumer, retired_at__isnull=True).only(
            "topic_key", "text"
        )
    )
    seen_topics = {_normalise(item.topic_key) for item in active}
    seen_texts = {_normalise(item.text) for item in active}
    sensitive = tuple(
        value.strip()
        for value in sources.sensitive_values
        if len(value.strip()) >= 4
    )
    now = timezone.now()
    accepted = []

    for item in batch:
        if len(accepted) >= batch_size:
            break
        text = _trim_words(str(item.get("text") or "").strip(), max_words)
        topic_key = str(item.get("topic_key") or "").strip()[:255]
        topic_norm = _normalise(topic_key)
        text_norm = _normalise(text)
        if not topic_norm or not text_norm:
            continue
        if topic_norm in seen_topics or text_norm in seen_texts:
            continue
        if any(_mentions_sensitive(text, value) for value in sensitive):
            continue
        run_id = str(item.get("source_run_id") or "").strip()
        source = None
        if run_id and run_id in allowed:
            source = Session.objects.filter(id=run_id, consumer=consumer).first()
        accepted.append((text, topic_key, source))
        seen_topics.add(topic_norm)
        seen_texts.add(text_norm)

    with transaction.atomic():
        for text, topic_key, source in accepted:
            UserInsight.objects.create(
                consumer=consumer,
                text=text,
                topic_key=topic_key,
                source_run=source,
                generated_at=now,
            )
        _retire_overflow(consumer, now)
        UserInsightCursor.objects.update_or_create(
            consumer=consumer,
            defaults={"source_fingerprint": fingerprint, "checked_at": now},
        )


def _retire_overflow(consumer, now) -> None:
    from ..setting.models import Setting

    from .models import UserInsight

    cap = Setting.get_insights_pool_cap()
    active = list(
        UserInsight.objects.filter(consumer=consumer, retired_at__isnull=True).order_by(
            "generated_at", "id"
        )
    )
    extra = len(active) - cap
    if extra <= 0:
        return
    for item in active[:extra]:
        item.retired_at = now
        item.in_hand = False
        item.save(update_fields=["retired_at", "in_hand", "updated_at"])


def _pick(active, shown: int, exclude_ids: set) -> list:
    ordered = _ordered(active)
    if not exclude_ids:
        return ordered[:shown]
    others = [item for item in ordered if item.id not in exclude_ids]
    if len(others) >= shown:
        return others[:shown]
    previous = [item for item in ordered if item.id in exclude_ids]
    return (others + previous)[:shown]


def _ordered(active) -> list:
    def key(item):
        return (
            item.last_shown_at is not None,
            item.last_shown_at or item.generated_at,
            item.show_count,
            item.generated_at,
            item.id,
        )

    return sorted(active, key=key)


def _stamp(chosen, active) -> None:
    now = timezone.now()
    chosen_ids = {item.id for item in chosen}
    for item in active:
        if item.id in chosen_ids:
            item.in_hand = True
            item.last_shown_at = now
            item.show_count = (item.show_count or 0) + 1
            item.save(update_fields=["in_hand", "last_shown_at", "show_count", "updated_at"])
        elif item.in_hand:
            item.in_hand = False
            item.save(update_fields=["in_hand", "updated_at"])


def _trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if max_words < 1 or len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _normalise(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _mentions_sensitive(text: str, value: str) -> bool:
    """Whole-word or whole-phrase match. Values under 4 characters are ignored."""
    phrase = (value or "").strip()
    if len(phrase) < 4 or not text:
        return False
    return re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE) is not None
