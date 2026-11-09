"""Temporary per-turn latency marks for the chat timing logs.

Delete this module together with the logger.info lines in
message/views.py and tasks.process_agent_response.
"""

import time


def elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _box(session) -> dict:
    box = getattr(session, "_chat_latency", None)
    if box is None:
        box = {
            "prompt_ms": 0,
            "retrieval_ms": 0,
            "history_ms": 0,
            "run_sync_ms": [],
            "insert_ms": 0,
            "on_model_turn_ms": 0,
        }
        session._chat_latency = box
    return box


def add_ms(session, key: str, started: float) -> None:
    if session is None:
        return
    box = _box(session)
    box[key] = int(box.get(key, 0)) + elapsed_ms(started)


def add_run_sync(session, started: float) -> None:
    if session is None:
        return
    _box(session)["run_sync_ms"].append(elapsed_ms(started))


def timing_fields(session) -> dict:
    box = getattr(session, "_chat_latency", None) or {}
    run_sync = [int(value) for value in (box.get("run_sync_ms") or [])]
    return {
        "prompt_ms": int(box.get("prompt_ms", 0)),
        "retrieval_ms": int(box.get("retrieval_ms", 0)),
        "history_ms": int(box.get("history_ms", 0)),
        "run_sync_ms": ",".join(str(value) for value in run_sync) if run_sync else "-",
        "retries": max(0, len(run_sync) - 1),
        "insert_ms": int(box.get("insert_ms", 0)),
        "on_model_turn_ms": int(box.get("on_model_turn_ms", 0)),
    }
