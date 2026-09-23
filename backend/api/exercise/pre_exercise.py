"""Pre-Exercise Prompt helpers (V2).

Distinct from ``Question.pre_exercise`` form flags. This module resolves
templating tokens, decides whether a returning-user check-in should run,
and supports the admin Test Prompt dry-run.
"""

from __future__ import annotations

import re
from typing import Optional

# Shared resolver lives in prompt_blocks. Kept so existing imports of TOKEN_PATTERN still match.
TOKEN_PATTERN = re.compile(
    r"\{\{\s*([a-zA-Z0-9_.]+)\s*(?:\|([^{}]*))?\}\}"
)

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


def build_token_context(consumer, exercise, session=None) -> dict[str, str]:
    """Flatten resolvable template tokens for pre-exercise instruction text."""
    from ..utils.prompt_blocks import build_token_context as _build

    return _build(consumer, exercise, session)


def resolve_template(text: Optional[str], context: dict[str, str]) -> str:
    """Replace ``{{token}}`` and ``{{token|fallback}}``. Unknown tokens become empty."""
    from ..utils.prompt_blocks import resolve_tokens

    return resolve_tokens(text, context)


def resolve_pre_exercise_fields(exercise, consumer, session=None) -> dict:
    """Return resolved description / instruction / goal for a consumer."""
    context = build_token_context(consumer, exercise, session)
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


def complete_pre_exercise_checkin(session, *, summary: Optional[str] = None, synthetic_text=None):
    """
    Handoff from check-in to Step 1: stamp completed_at + summary, advance
    current_step_no to 1, clear cached prompt, and start the exercise greeting.
    """
    from django.utils import timezone as dj_timezone

    if not session.in_pre_exercise_phase():
        raise ValueError("Session is not in the pre-exercise check-in phase")

    if summary is None:
        summary = generate_pre_exercise_summary(session)

    from django.conf import settings as django_settings

    from ..utils import Constants

    session.pre_exercise_prompt_summary = summary
    session.pre_exercise_completed_at = dj_timezone.now()
    session.current_step_no = 1
    session.cached_prompt = None
    update_fields = [
        "pre_exercise_prompt_summary",
        "pre_exercise_completed_at",
        "current_step_no",
        "cached_prompt",
        "updated_at",
    ]
    if django_settings.AI_STATE_MACHINE_ENABLED:
        session.state = Constants.SESSION_STATE_STEP_ACTIVE
        update_fields.append("state")
    session.save(update_fields=update_fields)

    from ..utils.AIWorkerClient import request_session_greeting

    return request_session_greeting(session, synthetic_text=synthetic_text)


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


def format_pre_exercise_prompt_block(exercise, consumer, session=None) -> str:
    """XML block injected into the system prompt during the check-in phase."""
    from django.conf import settings as django_settings

    resolved = resolve_pre_exercise_fields(exercise, consumer, session=session)
    if django_settings.AI_STATE_MACHINE_ENABLED:
        # step_no / is_step_complete are not in the flag-on output schema.
        # Telling the model to set them makes Gemini reject the turn.
        rules = """
            - Conduct a short conversational check-in only.
            - Do not begin Step 1 or any exercise step content.
            - Do not set step_goal_met or asks_readiness during the check-in.
            - When the check-in goal is met, invite the user to tap the start button;
              do not invent step progression yourself.
        """
        phase_note = "Do NOT start exercise steps yet. The app moves to Step 1 when the user taps Start."
    else:
        rules = """
            - Conduct a short conversational check-in only.
            - Do not begin Step 1 or any exercise step content.
            - Always set step_no to 0 and is_step_complete to false.
            - When the check-in goal is met, invite the user to tap the start button;
              do not invent step progression yourself.
        """
        phase_note = "Keep step_no at 0 and is_step_complete false until the user taps Start."
    return f"""
    <PRE_EXERCISE_CHECK_IN>
        <!-- You are in the pre-exercise check-in phase. Do NOT start exercise steps yet. -->
        <!-- {phase_note} -->
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
            {rules}
        </RULES>
    </PRE_EXERCISE_CHECK_IN>
    """
