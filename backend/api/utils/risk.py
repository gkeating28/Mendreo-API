"""Live risk: keyword pre-screen, model level, resources card, trust-and-safety mail."""

from __future__ import annotations

import json

from . import Constants

_RANK = {
    Constants.LIVE_RISK_LEVEL_NONE: 0,
    Constants.LIVE_RISK_LEVEL_LOW: 1,
    Constants.LIVE_RISK_LEVEL_MODERATE: 2,
    Constants.LIVE_RISK_LEVEL_HIGH: 3,
}


def normalize_risk_level(value) -> str:
    text = (value or "").strip().lower()
    if text in _RANK:
        return text
    return Constants.LIVE_RISK_LEVEL_NONE


def max_risk_level(left: str, right: str) -> str:
    left = normalize_risk_level(left)
    right = normalize_risk_level(right)
    return left if _RANK[left] >= _RANK[right] else right


def risk_prescreen(text: str) -> str:
    """Highest level whose keyword appears in the user's text."""
    from ..setting.models import Setting

    haystack = (text or "").casefold()
    if not haystack:
        return Constants.LIVE_RISK_LEVEL_NONE

    keywords = Setting.get_risk_keywords()
    matched = Constants.LIVE_RISK_LEVEL_NONE
    for level in (
        Constants.LIVE_RISK_LEVEL_LOW,
        Constants.LIVE_RISK_LEVEL_MODERATE,
        Constants.LIVE_RISK_LEVEL_HIGH,
    ):
        for phrase in keywords.get(level) or []:
            needle = str(phrase or "").strip().casefold()
            if needle and needle in haystack:
                matched = max_risk_level(matched, level)
    return matched


def apply_turn_risk(session, user_text: str, model_level) -> dict | None:
    """Raise the session's live level and return a resources card when needed."""
    level = max_risk_level(risk_prescreen(user_text), normalize_risk_level(model_level))
    current = normalize_risk_level(session.live_risk_level)
    updated = max_risk_level(current, level)
    if updated != current:
        session.live_risk_level = updated
        session.save(update_fields=["live_risk_level", "updated_at"])

    resources = None
    if level in (Constants.LIVE_RISK_LEVEL_MODERATE, Constants.LIVE_RISK_LEVEL_HIGH):
        resources = resources_payload(session)

    if level == Constants.LIVE_RISK_LEVEL_HIGH:
        from ..tasks import notify_trust_and_safety

        notify_trust_and_safety.delay_on_commit(session.id)

    return resources


def resources_payload(session) -> dict:
    """Resources card from the stamped or active ``resources`` prompt version."""
    from ..prompt.models import PromptVersion
    from .prompt_blocks import ensure_prompt_versions

    body = None
    meta = session.cached_prompt_meta or {}
    version = (meta.get("versions") or {}).get(Constants.PROMPT_KEY_RESOURCES)
    if version is not None:
        row = PromptVersion.objects.filter(
            key=Constants.PROMPT_KEY_RESOURCES,
            version=version,
        ).first()
        if row:
            body = row.body

    if body is None:
        chosen = ensure_prompt_versions()
        row = chosen.get(Constants.PROMPT_KEY_RESOURCES)
        body = row.body if row else json.dumps(Constants.DEFAULT_RESOURCES)

    return _parse_resources(body)


def _parse_resources(body: str) -> dict:
    try:
        parsed = json.loads(body or "")
    except (TypeError, ValueError):
        parsed = None

    if not isinstance(parsed, dict):
        return dict(Constants.DEFAULT_RESOURCES)

    links = []
    for item in parsed.get("links") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if label and url:
            links.append({"label": label, "url": url})

    title = str(parsed.get("title") or "").strip() or Constants.DEFAULT_RESOURCES["title"]
    text = str(parsed.get("body") or "").strip() or Constants.DEFAULT_RESOURCES["body"]
    if not links:
        links = list(Constants.DEFAULT_RESOURCES["links"])
    return {"title": title, "body": text, "links": links}
