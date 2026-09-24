"""Exercise and step authoring rules from API WP6."""

from __future__ import annotations

import re

from . import Constants

_PROGRESSION = re.compile(
    r"ready to (move on|proceed|continue)|next step|move on to",
    re.IGNORECASE,
)
_IMPERATIVES = ("summarise", "state", "list", "describe", "extract", "quote", "name")
_BOT = re.compile(r"the bot|you have", re.IGNORECASE)

PROMPT_SETTING_FIELDS = (
    "general_prompt",
    "therapeutic_prompt",
    "observations_instruction",
    "observations_tone_guide",
)


def progression_error(text: str) -> str | None:
    if text and _PROGRESSION.search(text):
        return (
            "Do not ask the user if they are ready or tell them to move on. "
            "Code asks that question."
        )
    return None


def completion_prompt_error(text: str) -> str | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    first = cleaned.split(None, 1)[0].strip(" :.,").casefold()
    if first not in _IMPERATIVES:
        return (
            "Start with an imperative: Summarise, State, List, Describe, Extract, Quote or Name."
        )
    if _BOT.search(cleaned):
        return "Write about the user. Do not mention the bot or say 'you have'."
    return None


def step_field_errors(data: dict) -> dict:
    errors = {}
    for field in ("instructions", "done_when"):
        message = progression_error(data.get(field) or "")
        if message:
            errors[field] = message
    prompt_error = completion_prompt_error(data.get("completion_prompt") or "")
    if prompt_error:
        errors["completion_prompt"] = prompt_error
    if data.get("result_field") and not (data.get("completion_prompt") or "").strip():
        errors["result_field"] = "A result field needs a completion prompt."
    duration = data.get("average_duration")
    if duration is not None and duration <= 0:
        errors["average_duration"] = "Duration must be greater than zero."
    return errors


def published_use_when_error(status: str | None, use_when: str | None) -> str | None:
    if status == Constants.EXERCISE_STATUS_PUBLISHED and not (use_when or "").strip():
        return "A published exercise needs use_when."
    return None


def authoring_warnings(exercise) -> list[dict]:
    findings = []
    steps = exercise.steps.prefetch_related("tags").all()
    for step in steps:
        for tag in step.tags.all():
            from ..asset.models import Asset

            if not Asset.objects.filter(tags=tag).exists():
                findings.append(
                    _finding(
                        exercise,
                        step,
                        "tags",
                        "warning",
                        f"Tag '{tag.name}' matches no assets.",
                    )
                )
    for question in exercise.questions.all():
        title = question.title or ""
        if "click" in title.casefold():
            findings.append(
                _finding(
                    exercise,
                    None,
                    "title",
                    "warning",
                    "Form question text contains 'click'.",
                    question=question,
                )
            )
    return findings


def lint_catalogue() -> dict:
    from ..exercise.models import Exercise

    findings = []
    for exercise in Exercise.objects.prefetch_related("steps__tags", "questions").order_by("order"):
        findings.extend(_exercise_findings(exercise))
        findings.extend(authoring_warnings(exercise))
    counts = {"error": 0, "warning": 0}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    return {"counts": counts, "findings": findings}


def _exercise_findings(exercise) -> list[dict]:
    findings = []
    use_when = published_use_when_error(exercise.status, exercise.use_when)
    if use_when:
        findings.append(_finding(exercise, None, "use_when", "error", use_when))
    for step in exercise.steps.all():
        data = {
            "instructions": step.instructions,
            "done_when": step.done_when,
            "completion_prompt": step.completion_prompt,
            "result_field": step.result_field_id,
            "average_duration": step.average_duration,
        }
        for field, message in step_field_errors(data).items():
            findings.append(_finding(exercise, step, field, "error", message))
    return findings


def _finding(exercise, step, field, severity, message, question=None) -> dict:
    return {
        "exercise_id": exercise.id,
        "exercise": exercise.title,
        "step_id": getattr(step, "id", None),
        "step": getattr(step, "title", None),
        "question_id": getattr(question, "id", None),
        "field": field,
        "severity": severity,
        "message": message,
    }
