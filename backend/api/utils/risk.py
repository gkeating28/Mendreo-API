"""Live risk: keyword pre-screen, model level, resources card, trust-and-safety mail."""

from __future__ import annotations

import json
import logging
import re

from django.utils import timezone

from . import Constants
from .risk_check import (
    ABOUT_FIGURE_OF_SPEECH,
    ABOUT_OTHER_PERSON,
    ABOUT_SELF_NOW,
    ABOUT_SELF_PAST,
    ABOUT_TOPIC_ONLY,
    ABOUT_UNCLEAR,
    RISK_CHECK_ABOUTS,
)

logger = logging.getLogger(__name__)

# A high turn is reclassified from the context check before any close or ratchet.
_CHECK_STAYS_HIGH = frozenset({ABOUT_SELF_NOW, ABOUT_UNCLEAR})
_CHECK_TO_MODERATE = frozenset({ABOUT_SELF_PAST})
_CHECK_TO_NONE = frozenset({
    ABOUT_OTHER_PERSON,
    ABOUT_FIGURE_OF_SPEECH,
    ABOUT_TOPIC_ONLY,
})

# A phrase is ignored when one of these sits within this many words before it.
# "dont" / "didnt" / "wouldnt" are the same words without an apostrophe.
_NEGATION_WINDOW_WORDS = 4
_NEGATIONS = (
    "do not",
    "no longer",
    "don't",
    "dont",
    "didn't",
    "didnt",
    "wouldn't",
    "wouldnt",
    "never",
    "not",
)
_NEGATION_RES = tuple(
    re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)") for phrase in _NEGATIONS
)
_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201b": "'",
        "\u02bc": "'",
        "\u2032": "'",
    }
)

_RANK = {
    Constants.LIVE_RISK_LEVEL_NONE: 0,
    Constants.LIVE_RISK_LEVEL_LOW: 1,
    Constants.LIVE_RISK_LEVEL_MODERATE: 2,
    Constants.LIVE_RISK_LEVEL_HIGH: 3,
}


def normalize_risk_level(value) -> str:
    text = (value or "").strip().lower()
    # The close-rating schema still says "critical". On a live turn that is high.
    if text == Constants.RISK_LEVEL_CRITICAL:
        return Constants.LIVE_RISK_LEVEL_HIGH
    if text in _RANK:
        return text
    return Constants.LIVE_RISK_LEVEL_NONE


def _normalise_risk_text(text: str) -> str:
    cleaned = (text or "").translate(_APOSTROPHES).casefold()
    return re.sub(r"\s+", " ", cleaned).strip()


def _negated_before(haystack: str, start: int) -> bool:
    window = " ".join(haystack[:start].split()[-_NEGATION_WINDOW_WORDS:])
    if not window:
        return False
    return any(pattern.search(window) for pattern in _NEGATION_RES)


def max_risk_level(left: str, right: str) -> str:
    left = normalize_risk_level(left)
    right = normalize_risk_level(right)
    return left if _RANK[left] >= _RANK[right] else right


def risk_prescreen(text: str) -> str:
    """Highest level whose phrase appears as whole words in the user's text.

    Curly apostrophes and extra spaces are normalised. A match is ignored when
    a negation sits within about four words before the phrase, so "I don't
    want to die" does not match "want to die". "I want to diet" does not match
    either: the phrase has to end on a word boundary.
    """
    from ..setting.models import Setting

    haystack = _normalise_risk_text(text)
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
            needle = _normalise_risk_text(str(phrase or ""))
            if not needle:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
            for found in pattern.finditer(haystack):
                if not _negated_before(haystack, found.start()):
                    matched = max_risk_level(matched, level)
                    break
    return matched


def _close_for_high_risk(session) -> None:
    """Stamp the close and the support-modal flag. Does not rate the session."""
    if getattr(session, "authoring_test", False):
        return

    updates = []
    if session.close_reason != Constants.CLOSE_REASON_HIGH_RISK:
        session.close_reason = Constants.CLOSE_REASON_HIGH_RISK
        updates.append("close_reason")
    if not session.closed_at:
        session.closed_at = timezone.now()
        updates.append("closed_at")
    if updates:
        updates.append("updated_at")
        session.save(update_fields=updates)

    consumer = getattr(session, "consumer", None)
    if consumer is not None and not consumer.crisis_notice_pending:
        consumer.crisis_notice_pending = True
        consumer.save(update_fields=["crisis_notice_pending", "updated_at"])


def level_after_risk_check(about: str) -> str:
    """Map a context-check verdict onto the level used for this turn.

    self_now and unclear stay high. self_past becomes the support card only.
    Someone else, a figure of speech, or the topic alone become none, so this
    turn does not raise the stored live level.
    """
    if about in _CHECK_STAYS_HIGH:
        return Constants.LIVE_RISK_LEVEL_HIGH
    if about in _CHECK_TO_MODERATE:
        return Constants.LIVE_RISK_LEVEL_MODERATE
    if about in _CHECK_TO_NONE:
        return Constants.LIVE_RISK_LEVEL_NONE
    return Constants.LIVE_RISK_LEVEL_HIGH


def _verdict_for_high_turn(session, user_text: str) -> dict:
    """Run the context check. Any failure stays self_now."""
    from .risk_check import check_whose_risk

    session_id = getattr(session, "id", None)
    try:
        verdict = check_whose_risk(session, user_text)
    except Exception as exc:  # noqa: BLE001 - a broken check must not leave a high turn open
        logger.warning(
            "risk check failed session=%s error=%s",
            session_id,
            type(exc).__name__,
        )
        verdict = None
    if not isinstance(verdict, dict):
        return {
            "about": ABOUT_SELF_NOW,
            "reason": "The check could not be completed.",
        }
    about = str(verdict.get("about") or "").strip()
    reason = str(verdict.get("reason") or "").strip()[:240]
    if about not in RISK_CHECK_ABOUTS:
        logger.warning("risk check invalid session=%s", session_id)
        about = ABOUT_SELF_NOW
        reason = reason or "The check could not be completed."
    return {"about": about, "reason": reason or "No reason given."}


def apply_turn_risk(session, user_text: str, model_level) -> dict | None:
    """Raise the session's live level and return a resources card when needed.

    A turn that would be high is checked first, unless this is an authoring
    preview. Moderate turns are unchanged and do not call the check.
    """
    level = max_risk_level(risk_prescreen(user_text), normalize_risk_level(model_level))
    if (
        level == Constants.LIVE_RISK_LEVEL_HIGH
        and not getattr(session, "authoring_test", False)
    ):
        verdict = _verdict_for_high_turn(session, user_text)
        session._risk_check = verdict
        level = level_after_risk_check(verdict["about"])

    current = normalize_risk_level(session.live_risk_level)
    updated = max_risk_level(current, level)
    if updated != current:
        session.live_risk_level = updated
        session.save(update_fields=["live_risk_level", "updated_at"])

    resources = None
    if level in (Constants.LIVE_RISK_LEVEL_MODERATE, Constants.LIVE_RISK_LEVEL_HIGH):
        resources = resources_payload(session)

    session._turn_risk_level = level
    if level == Constants.LIVE_RISK_LEVEL_HIGH and not getattr(session, "authoring_test", False):
        from ..tasks import notify_trust_and_safety

        notify_trust_and_safety.delay_on_commit(session.id)
        _close_for_high_risk(session)

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
