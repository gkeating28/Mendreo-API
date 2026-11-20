"""One place for the step numbers clients show on a session."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionProgress:
    completed_steps: int
    total_steps: int
    current_step_no: int | None


def prefetched_session_steps(session):
    """Steps already loaded on this instance, in ``order``.

    Returns None when ``session_steps`` was not prefetched. Callers then run
    their own query, so a chat turn or a freshly loaded session still sees
    the current rows. The returned list is a copy; the prefetch cache is left
    as it was loaded for this request.
    """
    cache = getattr(session, "_prefetched_objects_cache", None)
    if not cache or "session_steps" not in cache:
        return None
    return sorted(cache["session_steps"], key=lambda step: step.order)


def session_progress(session) -> SessionProgress:
    """Progress for one session, from its SessionStep rows.

    completed_steps counts SessionStep.completed. total_steps is the number
    of SessionStep rows on this run, or total_steps_no when those rows are
    not created yet. current_step_no is 0 during pre-exercise check-in, the
    1-based open step after that, and total_steps + 1 when the run is
    finished. A general chat keeps the stored current_step_no (null).
    """
    steps = prefetched_session_steps(session)
    if steps is None:
        steps = list(session.session_steps.all())
    completed_steps = sum(1 for step in steps if step.completed)
    if steps:
        total_steps = len(steps)
    else:
        total_steps = int(session.total_steps_no or 0)

    if not session.exercise_id:
        return SessionProgress(
            completed_steps=completed_steps,
            total_steps=total_steps,
            current_step_no=session.current_step_no,
        )

    if session.in_pre_exercise_phase():
        current_step_no = 0
    elif _run_finished(session, completed_steps, total_steps):
        current_step_no = total_steps + 1
    else:
        current_step_no = completed_steps + 1

    return SessionProgress(
        completed_steps=completed_steps,
        total_steps=total_steps,
        current_step_no=current_step_no,
    )


def _run_finished(session, completed_steps: int, total_steps: int) -> bool:
    if session.completed:
        return True
    return bool(total_steps) and completed_steps >= total_steps
