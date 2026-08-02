"""Pre-Exercise Prompt helpers (V2).

Distinct from ``Question.pre_exercise`` form flags. This module resolves
templating tokens, decides whether a returning-user check-in should run,
and supports the admin Test Prompt dry-run.
"""

from __future__ import annotations

import re
from typing import Optional

TOKEN_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")

DEFAULT_START_BUTTON_LABEL = "Start exercise"


def has_completed_exercise_before(consumer, exercise) -> bool:
    """Returning user for this exercise = at least one prior completed session."""
    from ..session.models import Session

    return Session.objects.filter(
        consumer=consumer,
        exercise=exercise,
        completed=True,
    ).exists()


def should_run_pre_exercise_checkin(consumer, exercise) -> bool:
    """
    Cadence decision (locked for Slice C):
    - every repeat for returning users (not first-ever run of this exercise)
    - same-day second runs also get check-in when a new session is created
    - incomplete same-day resume is handled by Session.get_or_create (no re-start)
    """
    if not exercise or not getattr(exercise, "pre_exercise_enabled", False):
        return False
    return has_completed_exercise_before(consumer, exercise)


def _last_completed_session(consumer, exercise):
    from ..session.models import Session

    return (
        Session.objects.filter(
            consumer=consumer,
            exercise=exercise,
            completed=True,
        )
        .order_by("-created_at")
        .first()
    )


def build_token_context(consumer, exercise) -> dict[str, str]:
    """Flatten resolvable template tokens for pre-exercise instruction text."""
    from ..knowledge.services import get_current_entries

    context: dict[str, str] = {
        "user.first_name": getattr(consumer.user, "first_name", "") or "",
        "user.last_name": getattr(consumer.user, "last_name", "") or "",
        "exercise.title": getattr(exercise, "title", "") or "",
        "exercise.subtitle": getattr(exercise, "subtitle", "") or "",
        "exercise.id": getattr(exercise, "id", "") or "",
    }

    last = _last_completed_session(consumer, exercise)
    if last:
        context["last_session.subject"] = last.subject or ""
        context["last_session.id"] = last.id
        if last.created_at:
            context["last_session.date"] = last.created_at.date().isoformat()
            context["last_session.completed_at"] = (
                last.pre_exercise_completed_at or last.updated_at or last.created_at
            ).isoformat()
        else:
            context["last_session.date"] = ""
            context["last_session.completed_at"] = ""
    else:
        context["last_session.subject"] = ""
        context["last_session.id"] = ""
        context["last_session.date"] = ""
        context["last_session.completed_at"] = ""

    for entry in get_current_entries(consumer, active_fields_only=True):
        key = entry.field.key
        context[f"knowledge.{key}"] = entry.value or ""

    return context


def resolve_template(text: Optional[str], context: dict[str, str]) -> str:
    """Replace ``{{token}}`` placeholders; unknown tokens become empty string."""
    if not text:
        return ""

    def _replace(match):
        token = match.group(1)
        return context.get(token, "")

    return TOKEN_PATTERN.sub(_replace, text)


def resolve_pre_exercise_fields(exercise, consumer) -> dict:
    """Return resolved description / instruction / goal for a consumer."""
    context = build_token_context(consumer, exercise)
    return {
        "pre_exercise_enabled": bool(exercise.pre_exercise_enabled),
        "description": resolve_template(exercise.pre_exercise_description, context),
        "instruction": resolve_template(exercise.pre_exercise_instruction, context),
        "goal": resolve_template(exercise.pre_exercise_goal, context),
        "completion_prompt": exercise.pre_exercise_completion_prompt or "",
        "start_button_label": exercise.pre_exercise_start_button_label
        or DEFAULT_START_BUTTON_LABEL,
        "resolved_tokens": context,
    }


def test_pre_exercise_prompt(exercise, consumer, *, run_dry_run: bool = False) -> dict:
    """
    Admin Test Prompt: resolve tokens against a real user; optional single-turn
    dry-run opening message (no persist).
    """
    resolved = resolve_pre_exercise_fields(exercise, consumer)
    payload = {
        "exercise_id": exercise.id,
        "consumer_id": getattr(consumer, "pk", None) or getattr(consumer, "user_id", None),
        "resolved": {
            "description": resolved["description"],
            "instruction": resolved["instruction"],
            "goal": resolved["goal"],
            "completion_prompt": resolved["completion_prompt"],
            "start_button_label": resolved["start_button_label"],
        },
        "tokens": resolved["resolved_tokens"],
        "dry_run": None,
    }

    if not run_dry_run:
        return payload

    # Lazy AI import — keep Vercel migrate path free of google.genai.
    from ..utils.AI import AI
    from pydantic import BaseModel, Field

    class OpeningMessage(BaseModel):
        text: str = Field(description="The assistant's opening check-in message")

    prompt = (
        "You are starting a pre-exercise check-in with a returning user. "
        "Produce only the opening assistant message (no step progression).\n\n"
        f"Description:\n{resolved['description']}\n\n"
        f"Instruction:\n{resolved['instruction']}\n\n"
        f"Goal:\n{resolved['goal']}\n\n"
        f"User first name: {resolved['resolved_tokens'].get('user.first_name', '')}\n"
    )
    result = AI.ask(prompt, OpeningMessage, temperature=0.4)
    payload["dry_run"] = {"opening_message": result.get("text")}
    return payload


def complete_pre_exercise_checkin(session, *, summary: Optional[str] = None):
    """
    Handoff from check-in to Step 1: stamp completed_at + summary, advance
    current_step_no to 1, clear cached prompt, and start the exercise greeting.
    """
    from django.utils import timezone as dj_timezone

    if not session.in_pre_exercise_phase():
        raise ValueError("Session is not in the pre-exercise check-in phase")

    if summary is None:
        summary = generate_pre_exercise_summary(session)

    session.pre_exercise_prompt_summary = summary
    session.pre_exercise_completed_at = dj_timezone.now()
    session.current_step_no = 1
    session.cached_prompt = None
    session.save(
        update_fields=[
            "pre_exercise_prompt_summary",
            "pre_exercise_completed_at",
            "current_step_no",
            "cached_prompt",
            "updated_at",
        ]
    )

    from ..utils.AIWorkerClient import request_session_greeting

    request_session_greeting(session)
    return session


def generate_pre_exercise_summary(session) -> str:
    """Build check-in summary via completion prompt + transcript (best-effort)."""
    exercise = session.exercise
    completion_prompt = (exercise.pre_exercise_completion_prompt or "").strip()
    if not completion_prompt:
        return "Pre-exercise check-in completed."

    from ..message.models import Message

    messages = (
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("created_at")
    )
    lines = []
    for message in messages:
        who = "User" if message.sender and message.sender.consumer_id else "Assistant"
        lines.append(f"{who}: {message.text}")
    transcript = "\n".join(lines) if lines else "(no messages yet)"

    try:
        from ..utils.AI import AI
        from pydantic import BaseModel, Field

        class SummaryResult(BaseModel):
            summary: str = Field(description="Short structured summary of the check-in")

        prompt = (
            f"{completion_prompt}\n\n"
            f"Check-in transcript:\n{transcript}\n\n"
            "Return a concise summary of the check-in."
        )
        result = AI.ask(prompt, SummaryResult, temperature=0.2)
        return (result.get("summary") or "").strip() or "Pre-exercise check-in completed."
    except Exception:
        return "Pre-exercise check-in completed."


def format_pre_exercise_prompt_block(exercise, consumer) -> str:
    """XML block injected into the system prompt during the check-in phase."""
    resolved = resolve_pre_exercise_fields(exercise, consumer)
    return f"""
    <PRE_EXERCISE_CHECK_IN>
        <!-- You are in the pre-exercise check-in phase. Do NOT start exercise steps yet. -->
        <!-- Keep step_no at 0 and is_step_complete false until the user taps Start. -->
        <DESCRIPTION>
            {resolved['description']}
        </DESCRIPTION>
        <INSTRUCTION>
            {resolved['instruction']}
        </INSTRUCTION>
        <GOAL>
            {resolved['goal']}
        </GOAL>
        <COMPLETION_PROMPT>
            {resolved['completion_prompt']}
        </COMPLETION_PROMPT>
        <START_BUTTON_LABEL>
            {resolved['start_button_label']}
        </START_BUTTON_LABEL>
        <RULES>
            - Conduct a short conversational check-in only.
            - Do not begin Step 1 or any exercise step content.
            - Always set step_no to 0 and is_step_complete to false.
            - When the check-in goal is met, invite the user to tap the start button;
              do not invent step progression yourself.
        </RULES>
    </PRE_EXERCISE_CHECK_IN>
    """
