"""Read-only view of the hard-coded prompt rules.

Nothing in this module is saved or logged. Callers attach the dict to an
admin response and then drop it.
"""

from __future__ import annotations

import contextvars
import importlib
import inspect
import re

_active = contextvars.ContextVar("prompt_debug_active", default=False)
_snap = contextvars.ContextVar("prompt_debug_snap", default=None)
_provider = contextvars.ContextVar("prompt_debug_provider", default=None)

_TURN_HINT = re.compile(r"<TURN_HINT>\n?(.*?)\n?</TURN_HINT>", re.DOTALL)
_RETRIEVED = re.compile(r"<RETRIEVED>(.*?)</RETRIEVED>", re.DOTALL)

# label, where it applies, module, attribute the running code reads.
# text_fn, when set, is called for the catalogue text. The line still
# points at `name`, which is the constant the runner uses.
_SPECS = (
    {
        "label": "programming_instructions",
        "applies": "every turn",
        "module": "api.utils.Constants",
        "name": "PROMPT_PROGRAMMING_INSTRUCTIONS",
    },
    {
        "label": "reply_length",
        "applies": "editable in Settings (reply_length)",
        "module": "api.utils.Constants",
        "name": "DEFAULT_REPLY_LENGTH_INSTRUCTION",
    },
    {
        "label": "one_question",
        "applies": "editable in Settings (one_question)",
        "module": "api.utils.Constants",
        "name": "DEFAULT_ONE_QUESTION_INSTRUCTION",
    },
    {
        "label": "client_knowledge_rule",
        "applies": "editable in Settings (client_knowledge_rule)",
        "module": "api.utils.Constants",
        "name": "DEFAULT_CLIENT_KNOWLEDGE_RULE",
    },
    {
        "label": "step_scope_rules",
        "applies": (
            "exercise only; the first-message sentence is omitted "
            "on the no-check-in opening turn"
        ),
        "module": "api.utils.Agent",
        "name": "STEP_SCOPE_RULES",
    },
    {
        "label": "on_step_fallback",
        "applies": "replaces the model's reply when an off-script retry still leaves the step",
        "module": "api.utils.turn_hint",
        "name": "ON_STEP_FALLBACK",
    },
    {
        "label": "stay_on_step_guard",
        "applies": "exercise only",
        "module": "api.utils.reply_style",
        "name": "reply_leaves_the_step",
        "text_fn": "stay_on_step_catalogue_text",
    },
    {
        "label": "client_summary_prompt",
        "applies": "editable in Settings (update_summary)",
        "module": "api.utils.summary_prompts",
        "name": "DEFAULT_UPDATE_SUMMARY_PROMPT",
    },
    {
        "label": "exercise_summary_prompt",
        "applies": "editable in Settings (update_exercise_summary)",
        "module": "api.utils.summary_prompts",
        "name": "DEFAULT_UPDATE_EXERCISE_SUMMARY_PROMPT",
    },
    {
        "label": "run_summary_prompt",
        "applies": "editable in Settings (run_summary_prompt)",
        "module": "api.utils.summary_prompts",
        "name": "DEFAULT_RUN_SUMMARY_PROMPT",
    },
    {
        "label": "restructuring_rewrite",
        "applies": "exercise only",
        "module": "api.utils.Agent",
        "name": "_UP_BACKGROUND_SENTENCE",
    },
    {
        "label": "onboarding_followup_rules",
        "applies": "general chat only",
        "module": "api.knowledge.followup",
        "name": "ONBOARDING_FOLLOWUP_RULES",
    },
    {
        "label": "pending_question",
        "applies": "every turn",
        "module": "api.utils.pending_question",
        "name": "PENDING_QUESTION_RULE",
    },
    {
        "label": "check_in_rules",
        "applies": "check-in only",
        "module": "api.exercise.pre_exercise",
        "name": "CHECK_IN_RULES",
    },
    {
        "label": "hidden_opener",
        "applies": (
            "start on a no-check-in step-1 open; the other lines after a "
            "check-in or on a later step"
        ),
        "module": "api.utils.SessionStateMachine",
        "name": "HIDDEN_OPENER_STEP_ONE",
        "text_fn": "hidden_opener_catalogue_text",
    },
)


class capture:
    """Turn the in-memory recorder on for one admin test call."""

    def __enter__(self):
        self._active_token = _active.set(True)
        self._snap_token = _snap.set({})
        self._provider_token = _provider.set(None)
        self.data = {}
        return self

    def __exit__(self, exc_type, exc, tb):
        self.data = dict(_snap.get() or {})
        _provider.reset(self._provider_token)
        _snap.reset(self._snap_token)
        _active.reset(self._active_token)
        return False


def capture_on() -> bool:
    return bool(_active.get())


def remember_turn(**fields) -> None:
    snap = _snap.get()
    if snap is None:
        return
    snap.update(fields)


def remember_reply(before, after) -> None:
    snap = _snap.get()
    if snap is None:
        return
    snap["reply_before"] = before
    snap["reply_after"] = after


def note_provider(provider) -> None:
    if _active.get():
        _provider.set(provider)


def take_provider():
    provider = _provider.get()
    _provider.set(None)
    return provider


def catalogue() -> list[dict]:
    """Live text of each hard-coded block. Read from the constants the runner uses."""
    rows = []
    for spec in _SPECS:
        module = importlib.import_module(spec["module"])
        path, line = _locate(module, spec["name"])
        if spec.get("text_fn"):
            text = getattr(module, spec["text_fn"])()
        else:
            text = getattr(module, spec["name"])
        rows.append(
            {
                "label": spec["label"],
                "text": text,
                "applies": spec["applies"],
                "file": path,
                "line": line,
            }
        )
    return rows


def build_debug(
    *,
    system_prompt,
    user_prompt,
    schema=None,
    model_name=None,
    retrieval_enabled=False,
    pending=None,
    reply_before=None,
    reply_after=None,
    refusal_reason=None,
    goal_missing=None,
    depth_gate_held=False,
    on_step_retried=False,
    on_step_held=False,
    extra_block_labels=(),
) -> dict:
    blocks = _included(system_prompt, user_prompt)
    present = {row["label"] for row in blocks}
    for label in extra_block_labels:
        if label in present:
            continue
        ref = _block_ref(label)
        ref["text"] = _block_text(label)
        blocks.append(ref)
        present.add(label)
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "output_schema": schema_text(schema),
        "turn_hint": _turn_hint(user_prompt),
        "retrieval_enabled": bool(retrieval_enabled),
        "retrieved_chunks": _chunks(user_prompt, pending),
        "model_name": model_name or None,
        "blocks": blocks,
        "reply_style": reply_style_report(reply_before, reply_after),
        "refusal_reason": refusal_reason,
        "goal_missing": goal_missing,
        "depth_gate_held": bool(depth_gate_held),
        "on_step_retried": bool(on_step_retried),
        "on_step_held": bool(on_step_held),
    }


def finish_debug(cap, session, refusal_reason=None, extra_block_labels=()) -> dict:
    """Build the response object from the in-memory snap, then drop the snap."""
    data = getattr(cap, "data", None) or {}
    goal_missing = getattr(session, "_debug_goal_missing", None)
    if not hasattr(session, "_debug_goal_missing"):
        goal_missing = None
    depth_held = bool(getattr(session, "_debug_depth_held", False))
    for attr in ("_debug_goal_missing", "_debug_depth_held"):
        if hasattr(session, attr):
            delattr(session, attr)

    retrieval_enabled = data.get("retrieval_enabled")
    if retrieval_enabled is None and session is not None:
        from ..grounding.retrieval import session_retrieval_enabled

        retrieval_enabled = session_retrieval_enabled(session)

    return build_debug(
        system_prompt=data.get("system_prompt"),
        user_prompt=data.get("user_prompt"),
        schema=data.get("schema"),
        model_name=data.get("model_name"),
        retrieval_enabled=retrieval_enabled,
        pending=data.get("pending"),
        reply_before=data.get("reply_before"),
        reply_after=data.get("reply_after"),
        refusal_reason=refusal_reason,
        goal_missing=goal_missing,
        depth_gate_held=depth_held,
        on_step_retried=bool(data.get("on_step_retried")),
        on_step_held=bool(data.get("on_step_held")),
        extra_block_labels=extra_block_labels,
    )


def schema_text(schema) -> str | None:
    if schema is None:
        return None
    lines = []
    for name, field in schema.model_fields.items():
        lines.append(f"{name}: {field.description or ''}")
    return "\n".join(lines)


def reply_style_report(before, after) -> dict:
    """Which cleaner rules changed `before` into `after`. Does not rewrite text."""
    if not before or before == after:
        return {"changed": False, "rules": []}
    from .reply_style import (
        _DASHES,
        _SPELLING_MAP,
        _SPELLING_PATTERN,
        _match_case,
        _strip_banned_openings,
    )

    rules = []
    dashed = before
    for dash, replacement in _DASHES.items():
        dashed = dashed.replace(dash, replacement)
    if dashed != before:
        rules.append("dash")

    def _spell(match: re.Match) -> str:
        word = match.group(0)
        return _match_case(word, _SPELLING_MAP[word.lower()])

    spelled = _SPELLING_PATTERN.sub(_spell, dashed)
    if spelled != dashed:
        rules.append("spelling")
    stripped = _strip_banned_openings(spelled)
    opened = stripped if stripped else spelled
    if opened != spelled:
        rules.append("opening strip")
    return {"changed": True, "rules": rules}


def _included(system_prompt, user_prompt) -> list[dict]:
    blob = f"{system_prompt or ''}\n{user_prompt or ''}"
    rows = []
    for spec in _SPECS:
        module = importlib.import_module(spec["module"])
        if not _spec_in(spec, module, blob):
            continue
        rows.append(_block_ref(spec["label"]))
    return rows


def _spec_in(spec, module, blob: str) -> bool:
    if spec["label"] == "hidden_opener":
        return _hidden_opener_in(module, blob)
    if spec.get("text_fn"):
        text = getattr(module, spec["text_fn"])()
    else:
        text = getattr(module, spec["name"])
    marker = _marker(text)
    return bool(marker) and marker in blob


def _hidden_opener_in(module, blob: str) -> bool:
    step_one = module.HIDDEN_OPENER_STEP_ONE
    later = module.HIDDEN_OPENER_LATER
    if step_one in blob or module.HIDDEN_OPENER_GREET_REPEAT in blob:
        return True
    if any(line.strip() == module.HIDDEN_OPENER_START for line in blob.splitlines()):
        return True
    head, _, tail = later.partition("{step_no}")
    return bool(head and tail and head in blob and tail in blob)


def _marker(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("-").strip()
        if len(stripped) >= 40 and "{" not in stripped:
            return stripped
    return (text or "").strip()


def _block_ref(label: str) -> dict:
    spec = next(row for row in _SPECS if row["label"] == label)
    module = importlib.import_module(spec["module"])
    path, line = _locate(module, spec["name"])
    return {"label": label, "file": path, "line": line}


def _block_text(label: str) -> str:
    spec = next(row for row in _SPECS if row["label"] == label)
    module = importlib.import_module(spec["module"])
    if spec.get("text_fn"):
        return getattr(module, spec["text_fn"])()
    return getattr(module, spec["name"])


def _turn_hint(user_prompt) -> str | None:
    found = [piece.strip() for piece in _TURN_HINT.findall(user_prompt or "") if piece.strip()]
    if not found:
        return None
    return "\n\n".join(found)


def _chunks(user_prompt, pending) -> list[dict]:
    """Titles as sent, plus source ids. Chunk text is left out."""
    body = _RETRIEVED.search(user_prompt or "")
    titles = []
    if body:
        for line in body.group(1).splitlines():
            if line.startswith("Title: "):
                titles.append(line[len("Title: "):])
    pending = list(pending or [])
    rows = []
    for index in range(max(len(titles), len(pending))):
        source_id = None
        if index < len(pending):
            source_id = pending[index].get("source_id")
        rows.append(
            {
                "title": titles[index] if index < len(titles) else "",
                "source_id": source_id,
            }
        )
    return rows


def _locate(module, name: str) -> tuple[str, int]:
    path = _rel(inspect.getsourcefile(module) or "")
    source = inspect.getsource(module).splitlines()
    for index, line in enumerate(source, 1):
        if line.startswith(f"{name} =") or line.startswith(f"{name}:"):
            return path, index
    obj = getattr(module, name)
    _, start = inspect.getsourcelines(obj)
    return path, start


def _rel(path: str) -> str:
    marker = "/backend/"
    if marker in path:
        return "backend/" + path.split(marker, 1)[1]
    return path
