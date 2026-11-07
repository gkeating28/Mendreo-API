"""Shape the stored prompt for the debug modal. Nothing here is saved."""

from __future__ import annotations

import re

# Longer names first so EXERCISE does not swallow EXERCISES.
_SYSTEM_TAGS = (
    "THERAPEUTIC_INSTRUCTIONS",
    "PROGRAMMING_INSTRUCTIONS",
    "EXERCISES",
    "EXERCISE",
    "GOALS",
    "TRIAGE",
    "SESSION_CONTEXT",
    "KNOWLEDGE",
    "FORM_ANSWERS",
    "ONBOARDING_FOLLOW_UP",
    "CLIENT_SUMMARY",
    "EXERCISE_SUMMARY",
    "DATE",
    "PENDING_QUESTION",
)
_USER_TAGS = ("RETRIEVED", "TURN_HINT")

_LAYER_META = {
    "THERAPEUTIC_INSTRUCTIONS": ("therapeutic_instructions", "Therapeutic instructions", "admin setting"),
    "PROGRAMMING_INSTRUCTIONS": ("programming_instructions", "Programming instructions", "system"),
    "EXERCISES": ("exercises", "Exercises", "exercise script"),
    "EXERCISE": ("exercise", "Exercise", "exercise script"),
    "GOALS": ("goals", "Goals", "admin setting"),
    "TRIAGE": ("triage", "Triage", "admin setting"),
    "SESSION_CONTEXT": ("session_context", "Session context", "user data"),
    "KNOWLEDGE": ("knowledge", "Knowledge", "user data"),
    "FORM_ANSWERS": ("form_answers", "Form answers", "user data"),
    "ONBOARDING_FOLLOW_UP": ("onboarding_follow_up", "Onboarding follow-up", "admin setting"),
    "CLIENT_SUMMARY": ("client_summary", "Client summary", "user data"),
    "EXERCISE_SUMMARY": ("exercise_summary", "Exercise summary", "user data"),
    "DATE": ("date", "Date", "system"),
    "PENDING_QUESTION": ("pending_question", "Pending question", "user data"),
    "RETRIEVED": ("retrieved", "Retrieved", "retrieval"),
    "TURN_HINT": ("turn_hint", "Turn hint", "system"),
}

_SYSTEM_PATTERN = re.compile(
    r"<(" + "|".join(_SYSTEM_TAGS) + r")>(.*?)</\1>",
    re.DOTALL,
)
_USER_PATTERN = re.compile(
    r"<(" + "|".join(_USER_TAGS) + r")>(.*?)</\1>",
    re.DOTALL,
)
_HINT_BODY = re.compile(r"<TURN_HINT>\n?(.*?)\n?</TURN_HINT>", re.DOTALL)

# Substrings of the hints _hinted_user_prompt can inject, in that function's order.
_LADDER = (
    {
        "key": "not_ready",
        "label": "Not ready",
        "markers": ("not ready to move on",),
        "won": "The person said they are not ready to move on.",
        "missed": "This turn was not a not-ready reply.",
    },
    {
        "key": "about_the_user",
        "label": "About the user",
        "markers": ("is asking what you know about them",),
        "won": "The user asked what Toni knows about them, and the client blocks had something to name.",
        "missed": "The message was not an about-you question, or the client blocks were empty.",
    },
    {
        "key": "finish_summary",
        "label": "Finish after confirmed summary",
        "markers": ("has confirmed the summary",),
        "won": "This is the last step, the summary was confirmed, and the goal is still open.",
        "missed": "This is not a last step with a confirmed summary and an open goal.",
    },
    {
        "key": "goal",
        "label": "Stored goal hint",
        "markers": ("This step is not done yet.", "This step is not done. Summarise"),
        "won": "A goal hint was waiting from the previous step check.",
        "missed": "No goal hint was waiting.",
    },
    {
        "key": "depth",
        "label": "Stored depth hint",
        "markers": ("The step's result is not yet specific enough",),
        "won": "A depth hint was waiting from the previous turn.",
        "missed": "No depth hint was waiting.",
    },
    {
        "key": "thin_answer",
        "label": "Thin answer",
        "markers": ("The reply was brief.", "You have already followed up twice"),
        "won": "The previous question was open and the reply was thin.",
        "won_accept": "The previous question was open, the reply was thin, and it had already been followed up twice.",
        "missed": "The previous question was not open, or the reply was not thin.",
    },
)


def approx_tokens(text: str) -> int:
    stripped = (text or "").strip()
    if not stripped:
        return 0
    return max(1, (len(stripped) + 3) // 4)


def prompt_layers(system_prompt: str, user_prompt: str) -> list[dict]:
    """Split the stored prompts on their tags. Leftover system text is one other layer."""
    layers = []
    leftover = []
    cursor = 0
    system = system_prompt or ""
    for match in _SYSTEM_PATTERN.finditer(system):
        gap = system[cursor:match.start()]
        if gap.strip():
            leftover.append(gap.strip())
        layers.append(_layer(match.group(1), match.group(2)))
        cursor = match.end()
    tail = system[cursor:]
    if tail.strip():
        leftover.append(tail.strip())
    if leftover:
        layers.append(
            {
                "key": "other",
                "label": "Other",
                "text": "\n\n".join(leftover),
                "tokens": approx_tokens("\n\n".join(leftover)),
                "source": "system",
            }
        )
    user = user_prompt or ""
    for match in _USER_PATTERN.finditer(user):
        layers.append(_layer(match.group(1), match.group(2)))
    return layers


def hint_ladder(user_prompt: str) -> dict:
    """Candidates in _hinted_user_prompt order, judged from the stored turn hint."""
    body = _hint_body(user_prompt)
    winner = _winner(body)
    candidates = []
    for spec in _LADDER:
        won = spec["key"] == winner
        if won:
            applicable = True
            reason = _won_reason(spec, body)
        elif winner is None:
            applicable = False
            reason = spec["missed"]
        elif _index(spec["key"]) < _index(winner):
            applicable = False
            reason = spec["missed"]
        else:
            applicable = False
            reason = "Not checked. An earlier hint was used."
        candidates.append(
            {
                "key": spec["key"],
                "label": spec["label"],
                "applicable": applicable,
                "won": won,
                "reason": reason,
            }
        )
    return {"winner": winner, "candidates": candidates}


def step_hold_decision(step_decision) -> dict:
    """One decisions entry from the step_decision already stored on the message."""
    if not isinstance(step_decision, dict):
        return {
            "type": "step_hold",
            "fired": False,
            "what": "No step hold or finish was recorded.",
            "why": "This turn did not judge an exercise step.",
            "inputs": {},
        }
    accepted = step_decision.get("accepted") if isinstance(step_decision.get("accepted"), dict) else {}
    model = step_decision.get("model") if isinstance(step_decision.get("model"), dict) else {}
    check = step_decision.get("check_done_when") if isinstance(step_decision.get("check_done_when"), dict) else {}
    goal = bool(accepted.get("step_goal_met"))
    asks = bool(accepted.get("asks_readiness"))
    held = bool(model.get("step_goal_met")) and not goal
    if asks and goal:
        what = "The step was accepted and readiness was asked."
        fired = True
    elif goal:
        what = "The step goal was accepted."
        fired = True
    elif held:
        what = "The step was held open."
        fired = True
    else:
        what = "The step stayed on the current work."
        fired = False
    missing = str(check.get("missing") or "").strip()
    if missing:
        why = f"Still missing: {missing}"
    elif check.get("forced"):
        why = "The done-when check was accepted after two earlier rejections."
    elif goal:
        why = "The done-when check passed."
    elif held:
        why = "The model's goal was not accepted."
    else:
        why = "The model did not mark the step goal met."
    return {
        "type": "step_hold",
        "fired": fired,
        "what": what,
        "why": why,
        "inputs": step_decision,
    }


def _layer(tag: str, inner: str) -> dict:
    key, label, source = _LAYER_META[tag]
    text = (inner or "").strip()
    return {
        "key": key,
        "label": label,
        "text": text,
        "tokens": approx_tokens(text),
        "source": source,
    }


def _hint_body(user_prompt: str) -> str:
    found = _HINT_BODY.findall(user_prompt or "")
    return "\n\n".join(piece.strip() for piece in found if piece and piece.strip())


def _winner(body: str) -> str | None:
    if not body:
        return None
    for spec in _LADDER:
        if any(marker in body for marker in spec["markers"]):
            return spec["key"]
    return None


def _won_reason(spec: dict, body: str) -> str:
    if spec["key"] == "thin_answer" and "You have already followed up twice" in body:
        return spec["won_accept"]
    return spec["won"]


def _index(key: str) -> int:
    for index, spec in enumerate(_LADDER):
        if spec["key"] == key:
            return index
    return len(_LADDER)
