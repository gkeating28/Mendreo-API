"""Admin-editable copy for a high-risk close.

A blank saved string falls back to the built-in default for that key.
The modal lines do the same, slot by slot. Read at request time so an
admin edit shows up without a deploy. The settings row is cached briefly,
and saving the row drops that cache.
"""

from __future__ import annotations

import json

from rest_framework import serializers

from . import Constants

TITLE_MAX = 120
BODY_MAX = 1000
CHAT_MAX = 2000
LABEL_MAX = 80
DETAIL_MAX = 240
MAX_LINES = 8

TEXT_KEYS = ("modal_title", "modal_body", "chat_message")
_TEXT_MAX = {
    "modal_title": TITLE_MAX,
    "modal_body": BODY_MAX,
    "chat_message": CHAT_MAX,
}

DEFAULT_HIGH_RISK_COPY = {
    "modal_title": "Support is available",
    "modal_body": (
        "It sounds like things are really hard right now. Please reach out "
        "to someone who can help. If you're in immediate danger, call 112 or "
        "999 or go to your nearest emergency department."
    ),
    "modal_lines": [
        {
            "label": "Samaritans",
            "detail": "116 123 (free, any time) or jo@samaritans.ie",
        },
        {
            "label": "Pieta",
            "detail": "1800 247 247 (free, any time) or text HELP to 51444",
        },
        {
            "label": "Text About It",
            "detail": "Text HELLO to 50808 (free, any time)",
        },
    ],
    "chat_message": (
        "I'm really concerned about you, and I want you to be safe. I'm going "
        "to close this chat so you can reach someone who can help right now. "
        "If you're in immediate danger, call 112 or 999. You can also call "
        "Samaritans free on 116 123, call Pieta on 1800 247 247, or text HELP "
        "to 51444 (Pieta) or HELLO to 50808 (Text About It). Please reach out "
        "to one of them now."
    ),
}


def _line(label: str, detail: str) -> dict:
    return {"label": label, "detail": detail}


def _merge_lines(stored, defaults: list) -> list:
    if not isinstance(stored, list):
        return [_line(item["label"], item["detail"]) for item in defaults]
    merged = []
    for index, default in enumerate(defaults):
        item = stored[index] if index < len(stored) and isinstance(stored[index], dict) else {}
        label = str(item.get("label") or "").strip()
        detail = str(item.get("detail") or "").strip()
        merged.append(_line(label or default["label"], detail or default["detail"]))
    for item in stored[len(defaults):]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        detail = str(item.get("detail") or "").strip()
        if label and detail:
            merged.append(_line(label, detail))
    return merged


def merge_high_risk_copy(stored) -> dict:
    """A blank saved string falls back to the built-in default for that key."""
    stored = stored if isinstance(stored, dict) else {}
    merged = {}
    for key in TEXT_KEYS:
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value
        else:
            merged[key] = DEFAULT_HIGH_RISK_COPY[key]
    merged["modal_lines"] = _merge_lines(
        stored.get("modal_lines"),
        DEFAULT_HIGH_RISK_COPY["modal_lines"],
    )
    return merged


def get_or_create_high_risk_copy():
    from ..setting.models import Setting

    setting, _ = Setting.objects.get_or_create(
        key=Constants.SETTING_KEY_HIGH_RISK_COPY,
        defaults={"value": json.dumps(DEFAULT_HIGH_RISK_COPY)},
    )
    return setting


def get_high_risk_copy() -> dict:
    """Effective copy. Blank saved values use the defaults."""
    from ..setting.models import Setting

    raw = Setting._cached_value(
        Constants.SETTING_KEY_HIGH_RISK_COPY,
        get_or_create_high_risk_copy,
    )
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = {}
    return merge_high_risk_copy(parsed)


def high_risk_chat_message() -> str:
    return get_high_risk_copy()["chat_message"]


def crisis_notice_payload(pending: bool) -> dict:
    """Modal copy only while the flag is set. Read at request time."""
    if not pending:
        return {"crisis_notice_pending": False}
    copy = get_high_risk_copy()
    return {
        "crisis_notice_pending": True,
        "modal_title": copy["modal_title"],
        "modal_body": copy["modal_body"],
        "modal_lines": copy["modal_lines"],
    }


def _validate_lines(value) -> list:
    if not isinstance(value, list):
        raise serializers.ValidationError("modal_lines must be a list.")
    if len(value) > MAX_LINES:
        raise serializers.ValidationError(f"modal_lines must have {MAX_LINES} items or fewer.")
    cleaned = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise serializers.ValidationError(f"modal_lines[{index}] must be an object.")
        unknown = set(item) - {"label", "detail"}
        if unknown:
            names = ", ".join(sorted(unknown))
            raise serializers.ValidationError(
                f"modal_lines[{index}] has unknown field(s): {names}."
            )
        label = item.get("label", "")
        detail = item.get("detail", "")
        if label is None:
            label = ""
        if detail is None:
            detail = ""
        if not isinstance(label, str) or not isinstance(detail, str):
            raise serializers.ValidationError(
                f"modal_lines[{index}] label and detail must be strings."
            )
        if len(label) > LABEL_MAX:
            raise serializers.ValidationError(
                f"modal_lines[{index}].label must be {LABEL_MAX} characters or fewer."
            )
        if len(detail) > DETAIL_MAX:
            raise serializers.ValidationError(
                f"modal_lines[{index}].detail must be {DETAIL_MAX} characters or fewer."
            )
        cleaned.append({"label": label, "detail": detail})
    return cleaned


def validate_high_risk_copy(value) -> dict:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object.")
    unknown = set(value) - set(TEXT_KEYS) - {"modal_lines"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise serializers.ValidationError(f"Unknown copy field(s): {names}.")

    cleaned = {}
    for key in TEXT_KEYS:
        if key not in value:
            continue
        text = value[key]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise serializers.ValidationError(f"{key} must be a string.")
        limit = _TEXT_MAX[key]
        if len(text) > limit:
            raise serializers.ValidationError(f"{key} must be {limit} characters or fewer.")
        cleaned[key] = text
    if "modal_lines" in value:
        cleaned["modal_lines"] = _validate_lines(value["modal_lines"])
    return cleaned
