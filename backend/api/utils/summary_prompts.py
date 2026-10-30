"""Stored summary instructions, with the session data added by the process."""

from __future__ import annotations

DEFAULT_UPDATE_SUMMARY_PROMPT = (
    "You are a helpful assistant training in the Unified Protocol that keeps a continuous summary of your client {name}.\n"
    "\n"
    "The summary covers {name} from their first session up to today. Each night you receive the previous overview, observations and next steps, plus the client's activity from the day. Update all three by incorporating the new information into them. Do not replace them. Keep everything already recorded that is still true, weigh each day against the whole history, and add what the day newly shows. Return each section in full.\n"
    "\n"
    "If the day adds nothing new, return the previous text unchanged.\n"
    "\n"
    "Observations are notes on exercises completed, whether the client wanted to do them, their state of mind, and any other relevant clinical observations. Next steps must always be included. Keep existing ones, and drop one only when the day shows it is done or no longer needed."
)

DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT = (
    "Update the notes for this exercise from the check-in and the step results."
)

DEFAULT_RUN_SUMMARY_PROMPT = (
    "Summarise this completed exercise for {name}.\n"
    "Write one short sentence, then three to five bullets of what they worked through.\n"
    "Stay with what they said in the check-in, the step results, and the transcript.\n"
    "Do not give advice, and do not add anything that is not in that material."
)

DEFAULT_RUN_SUMMARY_TONE_GUIDE = ""


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


def run_summary_prompt(
    instruction: str | None,
    name: str,
    tone: str | None,
    max_words: int,
    check_in: str | None,
    step_results: str | None,
    transcript: str | None,
) -> str:
    body = stored_instruction(instruction, DEFAULT_RUN_SUMMARY_PROMPT, name)
    parts = [
        body,
        "",
        f"Max length: about {max_words} words.",
    ]
    guide = (tone or "").strip()
    if guide:
        parts.append(f"Tone guide: {guide}")
    parts.extend(
        [
            "",
            f"Check-in summary:\n{check_in or '(none)'}",
            "",
            f"Step results:\n{step_results or '(none)'}",
            "",
            f"Transcript:\n{transcript or '(none)'}",
        ]
    )
    return "\n".join(parts)
