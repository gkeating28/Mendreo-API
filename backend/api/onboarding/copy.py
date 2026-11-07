"""Admin-editable Toni copy for each onboarding variant.

A blank saved string falls back to the built-in default for that key.
The {Hello|Hello Name} token picks the first alternative when the consumer
has no first name, and the second when they do. The word Name in the second
alternative is replaced with the first name.
"""

from __future__ import annotations

import json
import re

from rest_framework import serializers

from ..utils import Constants

COPY_TEXT_MAX = 500
SLIDER_LABEL_MAX = 64

COPY_TEXT_KEYS = (
    "header_title",
    "notice_start",
    "greeting",
    "notice_done",
    "closing_one",
    "closing_two",
    "complete_cta",
    "start_over",
    "composer_done",
    "empty",
)

SLIDER_LABELS = [
    "Really struggling",
    "Low",
    "Up and down",
    "Mostly okay",
    "Doing well",
]

_NAME_TOKEN = re.compile(r"\{([^{}|]+)\|([^{}|]+)\}")


def _variant_copy(**overrides) -> dict:
    base = {
        "header_title": "Getting to know you",
        "notice_start": "Getting to know you",
        "greeting": (
            "{Hello|Hello Name} — I'm Toni. Before we start working together, "
            "I'd like to understand a little about you."
        ),
        "notice_done": "Setup complete",
        "closing_one": (
            "{Thank you|Thank you, Name}. That gives me a real sense of where "
            "you are — I'll keep it in mind every time we talk."
        ),
        "closing_two": "Whenever you're ready, we can start with something small.",
        "complete_cta": "Continue",
        "start_over": "Start the conversation again",
        "composer_done": "Setup complete",
        "empty": "You're all set — there's nothing new to check in on right now.",
        "slider_labels": list(SLIDER_LABELS),
    }
    base.update(overrides)
    return base


# Current web and mobile strings, with {Hello|Hello Name} / {Thank you|Thank you, Name}.
# Welcome has no client string yet; these defaults are what an admin can edit.
DEFAULT_ONBOARDING_COPY = {
    Constants.KNOWLEDGE_FLOW_WELCOME: _variant_copy(
        header_title="Welcome",
        notice_start="Welcome",
        greeting="{Hello|Hello Name} — I'm Toni. A couple of things before we start.",
        notice_done="Welcome complete",
        closing_one="{Thank you|Thank you, Name}.",
        closing_two="Whenever you're ready, we can start getting to know you.",
        start_over="Start over",
        composer_done="Welcome complete",
        empty="You're all set — we can start getting to know you.",
    ),
    Constants.KNOWLEDGE_FLOW_INITIAL: _variant_copy(),
    Constants.KNOWLEDGE_FLOW_RETURN: _variant_copy(
        header_title="Check-in with Toni",
        notice_start="Check-in",
        greeting="{Hello|Hello Name} — good to see you. Let's take a moment to see how you are.",
        notice_done="Check-in complete",
        closing_one="{Thank you|Thank you, Name}. I'll keep that with me.",
        closing_two="Whenever you're ready, we can pick up in chat.",
        start_over="Start over",
        composer_done="Check-in complete",
    ),
    Constants.KNOWLEDGE_FLOW_REFRESH: _variant_copy(
        header_title="Check-in with Toni",
        notice_start="A deeper check-in",
        greeting=(
            "{Hello|Hello Name} — it's been a little while. "
            "I'd like to understand how things have been."
        ),
        notice_done="Check-in complete",
        closing_one=(
            "{Thank you|Thank you, Name}. That gives me a clearer sense of "
            "where you are now — I'll keep it in mind."
        ),
        closing_two="Whenever you're ready, we can pick up in chat.",
        start_over="Start over",
        composer_done="Check-in complete",
    ),
}


def resolve_name_token(text: str, first_name: str) -> str:
    name = (first_name or "").strip()

    def replace(match):
        without_name, with_name = match.group(1), match.group(2)
        if not name:
            return without_name
        return with_name.replace("Name", name)

    return _NAME_TOKEN.sub(replace, text or "")


def _merge_slider_labels(stored, defaults: list) -> list:
    # A blank slot falls back to that default label.
    if not isinstance(stored, list):
        return list(defaults)
    merged = []
    for index, default in enumerate(defaults):
        candidate = stored[index] if index < len(stored) else ""
        if isinstance(candidate, str) and candidate.strip():
            merged.append(candidate.strip())
        else:
            merged.append(default)
    return merged


def merge_onboarding_copy(variant: str, stored) -> dict:
    """A blank saved string falls back to the built-in default for that key."""
    defaults = DEFAULT_ONBOARDING_COPY[variant]
    stored = stored if isinstance(stored, dict) else {}
    merged = {}
    for key, default in defaults.items():
        if key == "slider_labels":
            merged[key] = _merge_slider_labels(stored.get(key), default)
            continue
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value
        else:
            merged[key] = default
    return merged


def _setting_key(variant: str) -> str:
    for key, flow in Constants.ONBOARDING_COPY_SETTING_KEYS.items():
        if flow == variant:
            return key
    raise KeyError(variant)


def get_or_create_onboarding_copy(variant: str):
    from ..setting.models import Setting

    setting, _ = Setting.objects.get_or_create(
        key=_setting_key(variant),
        defaults={"value": json.dumps(DEFAULT_ONBOARDING_COPY[variant])},
    )
    return setting


def get_onboarding_copy(variant: str) -> dict:
    """Effective copy for one variant. Blank saved values use the defaults."""
    from ..setting.models import Setting

    raw = Setting._cached_value(
        _setting_key(variant),
        lambda: get_or_create_onboarding_copy(variant),
    )
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        parsed = {}
    return merge_onboarding_copy(variant, parsed)


def resolved_flow_copy(variant: str, consumer) -> dict:
    merged = get_onboarding_copy(variant)
    user = getattr(consumer, "user", None)
    first_name = getattr(user, "first_name", "") if user is not None else ""
    resolved = {}
    for key, value in merged.items():
        if key == "slider_labels":
            resolved[key] = value
        else:
            resolved[key] = resolve_name_token(value, first_name)
    return resolved


def validate_copy_payload(value) -> dict:
    if not isinstance(value, dict):
        raise serializers.ValidationError("Must be an object.")
    unknown = set(value) - set(COPY_TEXT_KEYS) - {"slider_labels"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise serializers.ValidationError(f"Unknown copy field(s): {names}.")

    cleaned = {}
    for key in COPY_TEXT_KEYS:
        if key not in value:
            continue
        text = value[key]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise serializers.ValidationError(f"{key} must be a string.")
        if len(text) > COPY_TEXT_MAX:
            raise serializers.ValidationError(
                f"{key} must be {COPY_TEXT_MAX} characters or fewer."
            )
        # Blank is stored and the getter falls back to the default.
        cleaned[key] = text

    if "slider_labels" in value:
        labels = value["slider_labels"]
        if not isinstance(labels, list):
            raise serializers.ValidationError("slider_labels must be a list.")
        if len(labels) > len(SLIDER_LABELS):
            raise serializers.ValidationError(
                f"slider_labels must contain at most {len(SLIDER_LABELS)} labels."
            )
        cleaned_labels = []
        for label in labels:
            if not isinstance(label, str):
                raise serializers.ValidationError("Each slider label must be a string.")
            if len(label) > SLIDER_LABEL_MAX:
                raise serializers.ValidationError(
                    f"Each slider label must be {SLIDER_LABEL_MAX} characters or fewer."
                )
            cleaned_labels.append(label)
        cleaned["slider_labels"] = cleaned_labels

    return cleaned
