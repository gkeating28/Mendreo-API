"""Serialize completed exercise sessions as Reflect runs."""

from __future__ import annotations

import re

from django.db.models import Prefetch
from django.utils import timezone

from ..message.models import Message
from ..session.models import Session, SessionStep
from ..utils.Agent import is_usable_completion_result
from .models import SUMMARY_STEP_ID, ExerciseReflection

BASIS_KEYWORDS = {
    "Work": (
        "work",
        "job",
        "boss",
        "office",
        "colleague",
        "coworker",
        "team",
        "career",
        "meeting",
        "deadline",
        "manager",
        "restructure",
        "promotion",
    ),
    "Money": (
        "money",
        "rent",
        "debt",
        "bill",
        "pay",
        "paid",
        "financial",
        "broke",
        "mortgage",
        "bank",
        "afford",
    ),
    "Health": (
        "health",
        "sleep",
        "pain",
        "sick",
        "doctor",
        "illness",
        "body",
        "tired",
        "anxiety attack",
        "panic",
    ),
    "Relationships": (
        "relationship",
        "partner",
        "family",
        "friend",
        "mum",
        "mom",
        "dad",
        "wife",
        "husband",
        "kids",
        "child",
    ),
}

REFLECT_PROMPTS = {
    "overcome-worry": [
        (
            "Does this worry still feel as large?",
            "Name what still sticks, and what has loosened.",
        ),
        (
            "Was this worry practical, or hypothetical?",
            "Would you sort it the same way if it showed up tomorrow?",
        ),
        (
            "Could you still take that alternative action?",
            "What would make it easier to actually do.",
        ),
        (
            "What got in the way?",
            "One obstacle you could plan around next time.",
        ),
        (
            "Looking at the whole plan, what would you keep?",
            "The one move you'd want next time the worry starts.",
        ),
    ],
    "think-flexibly": [
        (
            "Does that thought still land the same way?",
            "Say what still feels true, and what you can now question.",
        ),
        (
            "Can you still see how it bends?",
            "The bias that is easiest to catch next time.",
        ),
        (
            "Is the other reading still available?",
            "A sentence you could try on when the old thought returns.",
        ),
        (
            "Which reading would you stand in now?",
            "The more useful thought, in your own words.",
        ),
    ],
    "stay-present": [
        (
            "What pulled you out of the moment?",
            "The cue you'd notice sooner next time.",
        ),
        (
            "What brought you back?",
            "The smallest thing that helped you return.",
        ),
        (
            "Could you use this again?",
            "When and where this practice would actually fit.",
        ),
    ],
}

DEFAULT_PROMPT = (
    "What stands out from this step?",
    "One sentence you'd want to remember the next time this shows up.",
)

SUMMARY_PROMPT = (
    "Looking at the whole run, what stands out?",
    "One sentence you'd want to read the next time this basis feels like this.",
)


def _slug(value: str) -> str:
    text = (value or "").lower().strip().replace("'", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _clip_finding(value: str | None) -> str | None:
    if not value or not is_usable_completion_result(value):
        return None
    return value.strip()


def _basis_from_text(text: str) -> str:
    blob = (text or "").lower()
    for name, keys in BASIS_KEYWORDS.items():
        if any(key in blob for key in keys):
            return name
    return "Other"


def _prompt_for(exercise_title: str, index: int) -> tuple[str, str]:
    rows = REFLECT_PROMPTS.get(_slug(exercise_title)) or []
    if 0 <= index < len(rows):
        return rows[index]
    return DEFAULT_PROMPT


def _transcript_buckets(messages: list[Message]) -> dict[int, list[dict]]:
    buckets: dict[int, list[dict]] = {}
    current = 1
    for message in sorted(messages, key=lambda item: item.created_at or timezone.now()):
        text = (message.text or "").strip()
        if not text:
            continue
        tagged = message.step_no or 0
        if message.is_step_complete:
            step = tagged if tagged >= 1 else current
            current = max(current, step + 1)
        else:
            step = tagged if tagged >= 1 else current
        sender = getattr(message, "sender", None)
        role = "user" if getattr(sender, "consumer_id", None) else "guide"
        buckets.setdefault(step, []).append({"role": role, "text": text})
    return buckets


def _serialize_reflection(row: ExerciseReflection) -> dict:
    return {
        "stepId": row.step_id,
        "text": row.text,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }


def _step_records(session: Session, include_transcript: bool) -> list[dict]:
    exercise = session.exercise
    catalogue = list(exercise.steps.order_by("order")) if exercise else []
    session_steps = list(session.session_steps.all())
    by_step_id = {}
    by_order = {}
    for row in session_steps:
        step = row.step
        if step:
            by_step_id[step.id] = row
            by_order[step.order] = row

    buckets = _transcript_buckets(list(session.messages.all())) if include_transcript else {}
    total = session.total_steps_no or (exercise.steps_no if exercise else 0) or len(session_steps)
    total = max(total, len(catalogue), 1)
    records = []
    title = (exercise.title if exercise else "") or "Exercise"

    for index in range(total):
        catalogue_step = catalogue[index] if index < len(catalogue) else None
        session_step = None
        if catalogue_step:
            session_step = by_step_id.get(catalogue_step.id)
        if session_step is None:
            session_step = by_order.get(index)
        step_id = (
            (catalogue_step.id if catalogue_step else None)
            or (session_step.step_id if session_step else None)
            or f"step-{index}"
        )
        step_title = (
            (catalogue_step.title if catalogue_step else None)
            or (getattr(getattr(session_step, "step", None), "title", None))
            or f"Step {index + 1}"
        )
        prompt, hint = _prompt_for(title, index)
        finding = _clip_finding(session_step.completion_result if session_step else None)
        completed_at = None
        if session_step and session_step.updated_at:
            completed_at = session_step.updated_at.isoformat()
        elif session.completed_at:
            completed_at = session.completed_at.isoformat()
        record = {
            "stepId": step_id,
            "title": step_title,
            "finding": finding,
            "reflectPrompt": prompt,
            "reflectHint": hint,
            "completedAt": completed_at,
        }
        if include_transcript:
            record["transcript"] = buckets.get(index + 1, [])
        records.append(record)
    return records


def serialize_run(session: Session, include_transcript: bool) -> dict:
    steps = _step_records(session, include_transcript=include_transcript)
    findings = " ".join(step["finding"] or "" for step in steps)
    topic = next((step["finding"] for step in steps if step["finding"]), None)
    topic = topic or (session.subject or "").strip() or (
        session.exercise.title if session.exercise else "This run"
    )
    basis = _basis_from_text(f"{topic} {findings}")
    reflections = [_serialize_reflection(row) for row in session.reflections.all()]
    exercise = session.exercise
    completed = session.completed_at or session.updated_at
    return {
        "id": session.id,
        "exerciseId": exercise.id if exercise else None,
        "exerciseName": exercise.title if exercise else "Exercise",
        "exerciseIcon": exercise.icon if exercise else None,
        "exerciseTint": (
            exercise.icon_background_color if exercise else None
        ),
        "exerciseOrder": exercise.order if exercise else 0,
        "basis": basis,
        "topic": topic,
        "completedAt": completed.isoformat() if completed else None,
        "steps": steps,
        "reflections": reflections,
    }


def completed_runs_queryset(consumer, include_messages=False):
    prefetches = [
        "reflections",
        Prefetch(
            "session_steps",
            queryset=SessionStep.objects.select_related("step").order_by("order"),
        ),
        "exercise__steps",
    ]
    if include_messages:
        prefetches.append(
            Prefetch(
                "messages",
                queryset=Message.objects.select_related("sender").order_by("created_at"),
            )
        )
    return (
        Session.objects.filter(
            consumer=consumer,
            completed=True,
            abandoned=False,
            exercise__isnull=False,
        )
        .select_related("exercise")
        .prefetch_related(*prefetches)
        .order_by("-completed_at", "-updated_at", "-id")
    )
