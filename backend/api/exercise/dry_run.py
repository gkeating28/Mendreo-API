"""Admin dry-run of one step. The temporary session is removed afterwards."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..session.models import Session, SessionStep
from ..utils import Constants
from ..utils.AI import AI
from ..utils.Agent import _prepare_prompt


class _Opening(BaseModel):
    text: str = Field(description="The assistant's opening message for this step")


def dry_run_step(exercise, step, consumer, transcript: str | None = None) -> dict:
    session = Session.objects.create(
        consumer=consumer,
        exercise=exercise,
        current_step_no=step.order + 1,
        total_steps_no=exercise.steps_no,
        state=Constants.SESSION_STATE_STEP_ACTIVE,
        subject="Dry run",
    )
    SessionStep.create(session, exercise)
    try:
        prompt = _prepare_prompt(session)
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
            "step_id": step.id,
            "prompt": prompt,
            "opening_message": result.get("text"),
        }
    finally:
        session.delete()
