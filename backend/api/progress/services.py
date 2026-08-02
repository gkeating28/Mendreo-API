"""Progress & Insights services (Slice E)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from django.utils import timezone
from rest_framework import serializers

from ..knowledge.models import KnowledgeEntry, KnowledgeField, KnowledgeQuestion
from ..session.models import Session
from ..setting.models import Setting
from ..utils import Constants, DateUtils
from .models import UserObservation


def parse_date_range(request) -> tuple[date, date]:
    """
    Parse ?from=&to= ISO dates. Default = current calendar week (Mon–Sun)
    in Django TIME_ZONE. Reject inverted ranges and spans > ~12 months.
    """
    from_param = request.query_params.get("from") or request.query_params.get("from_date")
    to_param = request.query_params.get("to") or request.query_params.get("to_date")

    today = DateUtils.local_date()
    if from_param or to_param:
        if not from_param or not to_param:
            raise serializers.ValidationError(
                {"detail": "Both 'from' and 'to' query params are required together."}
            )
        try:
            start = DateUtils.parse_date(from_param)
            end = DateUtils.parse_date(to_param)
        except Exception:
            raise serializers.ValidationError(
                {"detail": "Invalid date format. Use YYYY-MM-DD."}
            )
    else:
        # Monday of current week → Sunday
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)

    if end < start:
        raise serializers.ValidationError({"detail": "'to' must be on or after 'from'."})

    if (end - start).days > Constants.PROGRESS_MAX_RANGE_DAYS:
        raise serializers.ValidationError(
            {"detail": f"Date range cannot exceed {Constants.PROGRESS_MAX_RANGE_DAYS} days."}
        )

    return start, end


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _range_bounds(start: date, end: date):
    range_start, _ = DateUtils.day_bounds(start)
    _, range_end = DateUtils.day_bounds(end)
    return range_start, range_end


def _mood_field():
    return KnowledgeField.objects.filter(key=Constants.PROGRESS_MOOD_FIELD_KEY).first()


def _stress_field():
    return KnowledgeField.objects.filter(key=Constants.PROGRESS_STRESS_FIELD_KEY).first()


def _slider_value_labels(field) -> list[str]:
    if not field:
        return []
    question = (
        KnowledgeQuestion.objects.filter(
            target_field=field,
            active=True,
            response_type=Constants.KNOWLEDGE_RESPONSE_TYPE_SLIDER,
        )
        .order_by("order", "created_at")
        .first()
    )
    if question and question.value_labels:
        return list(question.value_labels)
    return []


def get_mood_progress(consumer, start: date, end: date) -> dict:
    field = _mood_field()
    labels = _slider_value_labels(field)
    points = []

    if field:
        range_start, range_end = _range_bounds(start, end)
        entries = (
            KnowledgeEntry.objects.filter(
                consumer=consumer,
                field=field,
                created_at__gte=range_start,
                created_at__lt=range_end,
            )
            .order_by("created_at")
        )
        by_day = {}
        for entry in entries:
            day = DateUtils.local_date(entry.created_at)
            try:
                value = int(entry.value)
            except (TypeError, ValueError):
                continue
            if value < Constants.SLIDER_MIN or value > Constants.SLIDER_MAX:
                continue
            label = ""
            if 0 <= value < len(labels):
                label = labels[value] or ""
            by_day[day] = {
                "date": day.isoformat(),
                "value": value,
                "value_scaled": value * 10,
                "label": label,
            }
        points = [by_day[d] for d in sorted(by_day.keys())]

    check_in_count = len(points)
    sparse = check_in_count < 2
    empty = check_in_count == 0

    summary = None
    if check_in_count > 0:
        values = [p["value"] for p in points]
        average = round(sum(values) / len(values), 2)

        period_days = (end - start).days + 1
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)
        prev_points = _mood_points_only(consumer, field, prev_start, prev_end, labels)
        prev_avg = None
        if prev_points:
            prev_avg = sum(p["value"] for p in prev_points) / len(prev_points)
        delta = None if prev_avg is None else round(average - prev_avg, 2)

        summary = {
            "average": average,
            "delta": delta,
            "check_in_count": check_in_count,
        }

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "points": points,
        "summary": summary,
        "empty": empty,
        "sparse": sparse,
        "return_onboarding_cta": sparse,
    }


def _mood_points_only(consumer, field, start, end, labels):
    if not field:
        return []
    range_start, range_end = _range_bounds(start, end)
    entries = (
        KnowledgeEntry.objects.filter(
            consumer=consumer,
            field=field,
            created_at__gte=range_start,
            created_at__lt=range_end,
        )
        .order_by("created_at")
    )
    by_day = {}
    for entry in entries:
        day = DateUtils.local_date(entry.created_at)
        try:
            value = int(entry.value)
        except (TypeError, ValueError):
            continue
        label = ""
        if 0 <= value < len(labels):
            label = labels[value] or ""
        by_day[day] = {"date": day.isoformat(), "value": value, "label": label}
    return [by_day[d] for d in sorted(by_day.keys())]


def get_exercises_progress(consumer, start: date, end: date) -> dict:
    range_start, range_end = _range_bounds(start, end)
    sessions = (
        Session.objects.filter(
            consumer=consumer,
            completed=True,
            exercise__isnull=False,
            created_at__gte=range_start,
            created_at__lt=range_end,
        )
        .select_related("exercise")
        .order_by("created_at")
    )

    completed_days = set()
    by_exercise = {}
    total = 0
    for session in sessions:
        total += 1
        day = DateUtils.local_date(session.created_at)
        completed_days.add(day)
        exercise = session.exercise
        row = by_exercise.get(exercise.id)
        if not row:
            row = {
                "exercise_id": exercise.id,
                "title": exercise.title,
                "icon": exercise.icon,
                "icon_svg": exercise.icon_svg,
                "icon_background_color": exercise.icon_background_color,
                "completions": 0,
                "last_completed_at": session.created_at,
            }
            by_exercise[exercise.id] = row
        row["completions"] += 1
        if session.created_at > row["last_completed_at"]:
            row["last_completed_at"] = session.created_at

    breakdown = sorted(
        by_exercise.values(),
        key=lambda r: (-r["completions"], r["title"]),
    )
    for row in breakdown:
        row["last_completed_at"] = row["last_completed_at"].isoformat()

    heatmap = [
        {"date": d.isoformat(), "completed": d in completed_days}
        for d in _daterange(start, end)
    ]

    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_completions": total,
        "heatmap": heatmap,
        "breakdown": breakdown,
        "empty": total == 0,
    }


def get_patterns_progress(consumer, start: date, end: date) -> dict:
    enabled = Setting.get_observations_enabled()
    observation = None
    if enabled:
        latest = UserObservation.latest_for(consumer)
        if latest:
            observation = {
                "text": latest.text,
                "topic_tag": latest.topic_tag,
                "generated_at": latest.generated_at.isoformat(),
                "chat_seed": f"I'd like to talk about this: {latest.text}",
            }

    stress_points = _aggregate_stress_points(consumer, start, end)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "observations_enabled": enabled,
        "observation": observation,
        "stress_points": stress_points,
    }


def _aggregate_stress_points(consumer, start: date, end: date) -> list[dict]:
    field = _stress_field()
    if not field:
        return []

    range_start, range_end = _range_bounds(start, end)
    entries = KnowledgeEntry.objects.filter(
        consumer=consumer,
        field=field,
        created_at__gte=range_start,
        created_at__lt=range_end,
    ).order_by("-created_at")

    counts = defaultdict(int)
    recent_dates = defaultdict(list)
    for entry in entries:
        day = DateUtils.local_date(entry.created_at).isoformat()
        for part in [p.strip() for p in (entry.value or "").split(",") if p.strip()]:
            counts[part] += 1
            if day not in recent_dates[part]:
                recent_dates[part].append(day)

    rows = [
        {
            "category": category,
            "count": count,
            "recent_dates": recent_dates[category][:5],
        }
        for category, count in counts.items()
        if count > 0
    ]
    rows.sort(key=lambda r: (-r["count"], r["category"]))
    return rows


def get_streaks(consumer) -> dict:
    mood_days = _activity_days_mood(consumer)
    exercise_days = _activity_days_exercise(consumer)
    return {
        "check_in": _streak_stats(mood_days),
        "exercise": _streak_stats(exercise_days),
        "copy": Constants.PROGRESS_STREAK_COPY,
    }


def _activity_days_mood(consumer) -> set[date]:
    field = _mood_field()
    if not field:
        return set()
    days = set()
    for created_at in KnowledgeEntry.objects.filter(
        consumer=consumer, field=field
    ).values_list("created_at", flat=True):
        days.add(DateUtils.local_date(created_at))
    return days


def _activity_days_exercise(consumer) -> set[date]:
    days = set()
    for created_at in Session.objects.filter(
        consumer=consumer,
        completed=True,
        exercise__isnull=False,
    ).values_list("created_at", flat=True):
        days.add(DateUtils.local_date(created_at))
    return days


def _streak_stats(days: set[date]) -> dict:
    if not days:
        return {"current": 0, "best": 0}

    sorted_days = sorted(days)
    best = 1
    run = 1
    for i in range(1, len(sorted_days)):
        if sorted_days[i] == sorted_days[i - 1] + timedelta(days=1):
            run += 1
            best = max(best, run)
        else:
            run = 1

    today = DateUtils.local_date()
    current = 0
    cursor = today
    # Allow streak to still count if last activity was yesterday (day not over)
    # Spec: breaks at midnight if no activity that day — current streak ends
    # if today has no activity yet? Spec says consecutive days with activity.
    # Current = count back from today if today active, else from yesterday.
    if today not in days:
        cursor = today - timedelta(days=1)
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)

    return {"current": current, "best": max(best, current)}


# --- Observation generation ---


class ObservationResult:
    def __init__(self, text: str, topic_tag: str):
        self.text = text
        self.topic_tag = topic_tag


def should_generate_observation(consumer) -> bool:
    if not Setting.get_observations_enabled():
        return False
    latest = UserObservation.latest_for(consumer)
    if not latest:
        return True
    return timezone.now() - latest.generated_at >= timedelta(hours=24)


def generate_observation_for_consumer(consumer) -> Optional[UserObservation]:
    """
    Generate at most one observation per 24h. On failure, retain prior row.
    """
    if not should_generate_observation(consumer):
        return UserObservation.latest_for(consumer)

    try:
        result = _run_observation_ai(consumer)
        if not result or not (result.text or "").strip():
            return UserObservation.latest_for(consumer)

        max_words = Setting.get_observations_max_length()
        text = _trim_words(result.text.strip(), max_words)
        return UserObservation.objects.create(
            consumer=consumer,
            text=text,
            topic_tag=(result.topic_tag or "").strip()[:255],
            generated_at=timezone.now(),
        )
    except Exception:
        return UserObservation.latest_for(consumer)


def _trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _run_observation_ai(consumer) -> ObservationResult:
    from pydantic import BaseModel, Field
    from ..utils.AI import AI
    from ..knowledge.services import get_current_knowledge_summary

    knowledge = get_current_knowledge_summary(consumer, include_sensitive=True)
    transcript = _recent_transcript_excerpt(consumer, days=7)
    instruction = Setting.get_observations_instruction()
    tone = Setting.get_observations_tone_guide()
    max_words = Setting.get_observations_max_length()

    class Schema(BaseModel):
        text: str = Field(description="Second-person observation paragraph")
        topic_tag: str = Field(description="Short topic tag, e.g. work anxiety")

    prompt = (
        f"{instruction}\n\n"
        f"Tone guide: {tone}\n"
        f"Max length: about {max_words} words.\n\n"
        f"<KNOWLEDGE>\n{knowledge}\n</KNOWLEDGE>\n\n"
        f"<RECENT_TRANSCRIPTS>\n{transcript}\n</RECENT_TRANSCRIPTS>\n"
    )
    data = AI.ask(prompt, Schema, temperature=0.4)
    return ObservationResult(
        text=data.get("text", ""),
        topic_tag=data.get("topic_tag", ""),
    )


def _recent_transcript_excerpt(consumer, days: int = 7) -> str:
    from ..message.models import Message

    start = timezone.now() - timedelta(days=days)
    messages = (
        Message.objects.filter(session__consumer=consumer, created_at__gte=start)
        .select_related("sender", "session")
        .order_by("created_at")[:200]
    )
    lines = []
    for message in messages:
        who = "User" if message.sender and message.sender.consumer_id else "Assistant"
        text = (message.text or "")[:280]
        lines.append(f"{who}: {text}")
    return "\n".join(lines) if lines else "(no recent messages)"
