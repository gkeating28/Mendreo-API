"""Admin dry-run of one step. The temporary session is removed afterwards."""

from __future__ import annotations

from types import SimpleNamespace

from pydantic import BaseModel, Field

from ..session.models import Session, SessionStep
from ..utils import Constants
from ..utils.AI import AI
from ..utils.Agent import _prepare_prompt

_TEXT_FIELDS = (
    "title",
    "description",
    "instructions",
    "reference_material",
    "done_when",
)


class _Opening(BaseModel):
    text: str = Field(description="The assistant's opening message for this step")


def step_fields_from_data(data) -> tuple[dict | None, str | None]:
    """Copy request step text. Returns (fields, error). Nothing here is saved."""
    if not isinstance(data, dict):
        return {}, None
    fields = {}
    for name in _TEXT_FIELDS:
        if name in data and data[name] is not None:
            fields[name] = str(data[name])
    if "order" in data and data["order"] is not None and data["order"] != "":
        try:
            fields["order"] = int(data["order"])
        except (TypeError, ValueError):
            return None, "Order must be a whole number."
    return fields, None


def _copy_step(step) -> SimpleNamespace:
    return SimpleNamespace(
        id=getattr(step, "id", None),
        title=step.title or "",
        description=step.description or "",
        instructions=step.instructions or "",
        reference_material=getattr(step, "reference_material", None) or "",
        done_when=getattr(step, "done_when", None) or "",
        order=step.order if step.order is not None else 0,
        key=getattr(step, "key", None),
        completion_prompt=getattr(step, "completion_prompt", None) or "",
    )


def _apply_fields(step: SimpleNamespace, fields: dict) -> SimpleNamespace:
    for name, value in fields.items():
        setattr(step, name, value)
    return step


def steps_for_dry_run(exercise, step, fields: dict | None):
    """Saved steps as plain copies, with request text applied. Never writes Step rows."""
    fields = fields or {}
    rows = [_copy_step(row) for row in exercise.steps.order_by("order")]
    if step is None:
        live = _apply_fields(
            SimpleNamespace(
                id=None,
                title="",
                description="",
                instructions="",
                reference_material="",
                done_when="",
                order=len(rows),
                key=None,
                completion_prompt="",
            ),
            fields,
        )
        rows.append(live)
    else:
        live = next((row for row in rows if row.id == step.id), None)
        if live is None:
            live = _apply_fields(_copy_step(step), fields)
            rows.append(live)
        else:
            _apply_fields(live, fields)
    rows.sort(key=lambda row: row.order if row.order is not None else 0)
    live_index = next(index for index, row in enumerate(rows) if row is live)
    return rows, live, live_index


def dry_run_step(exercise, step, consumer, transcript: str | None = None, step_fields=None) -> dict:
    rows, live, live_index = steps_for_dry_run(exercise, step, step_fields)
    session = None
    try:
        session = Session.objects.create(
            consumer=consumer,
            exercise=exercise,
            current_step_no=live_index + 1,
            total_steps_no=len(rows),
            state=Constants.SESSION_STATE_STEP_ACTIVE,
            subject="Dry run",
        )
        SessionStep.create(session, exercise)
        prompt = _prepare_prompt(session, steps=rows, create_summary=False)
        if transcript:
            prompt = f"{prompt}\n\nTranscript so far:\n{transcript}"
        result = AI.ask(
            (
                f"{prompt}\n\n"
                "Write only the opening message for the live step. One or two sentences."
            ),
            _Opening,
            temperature=0.4,
        )
        return {
            "exercise_id": exercise.id,
            "step_id": live.id,
            "prompt": prompt,
            "opening_message": result.get("text"),
        }
    finally:
        if session is not None:
            SessionStep.objects.filter(session=session).delete()
            session.delete()
