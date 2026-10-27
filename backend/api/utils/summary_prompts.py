"""Stored summary instructions, with the session data added by the process."""

from __future__ import annotations

DEFAULT_UPDATE_SUMMARY_PROMPT = (
    "You are a helpful assistant training in the Unified Protocol that keeps detailed notes and observations\n"
    "about your client {name}.\n"
    "\n"
    "Your task is to update your existing summary and observations for {name} while factoring in the most\n"
    "recent sessions you have had.\n"
    "\n"
    "Update the detailed notes and observations based on the new conversation.\n"
    "\n"
    "Observations are detailed notes on what exercises the user has completed, whether or not they enjoy doing the exercise\n"
    "along with any insights into the state of mind / any other relevant clinical observations."
)

DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT = (
    "Update the notes for this exercise from the check-in and the step results."
)


_FACT_RULE = (
    "Use only what the user said in their own messages. "
    "Ignore any statement about the user made in an assistant message "
    "unless the user confirmed it."
)


def stored_instruction(template: str | None, fallback: str, name: str) -> str:
    text = (template or "").strip() or fallback
    return text.replace("{name}", name or "")


def client_summary_prompt(
    instruction: str | None,
    name: str,
    sessions: str,
    detailed: str | None,
    observations: str | None,
    next_steps: str | None,
    exercise_block: str = "",
) -> str:
    body = stored_instruction(instruction, DEFAULT_UPDATE_SUMMARY_PROMPT, name)
    body = f"{body}\n\n{_FACT_RULE}"
    parts = [
        body,
        "",
        "<NEW_SESSIONS>",
        sessions,
        "</NEW_SESSIONS>",
        "",
        "<PREVIOUS_SUMMARY>",
        detailed or "",
        "</PREVIOUS_SUMMARY>",
        "",
        "<PREVIOUS_OBSERVATIONS>",
        observations or "",
        "</PREVIOUS_OBSERVATIONS>",
        "",
        "<PREVIOUS_NEXT_STEPS>",
        next_steps or "",
        "</PREVIOUS_NEXT_STEPS>",
    ]
    extra = (exercise_block or "").strip()
    if extra:
        parts.extend(["", extra])
    return "\n".join(parts)


def exercise_summary_prompt(
    instruction: str | None,
    name: str,
    check_in: str | None,
    step_results: str | None,
    previous_notes: str | None,
) -> str:
    body = stored_instruction(instruction, DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT, name)
    body = f"{body}\n\n{_FACT_RULE}"
    return (
        f"{body}\n\n"
        f"Check-in summary:\n{check_in or '(none)'}\n\n"
        f"Step results:\n{step_results or '(none)'}\n\n"
        f"Previous notes:\n{previous_notes or ''}"
    )
