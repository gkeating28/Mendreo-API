"""Make a model reply match the writing rules the prompt already states."""

from __future__ import annotations

import re

_DASHES = {
    "\u2014": " - ",
    "\u2013": "-",
    "\u2003": " ",
    "\u2002": " ",
    "\u2001": " ",
    "\u2000": " ",
}

# Longer forms first so "recognized" is not partly matched as "recognize".
_SPELLINGS = (
    ("recognizing", "recognising"),
    ("recognized", "recognised"),
    ("recognizes", "recognises"),
    ("recognize", "recognise"),
    ("behaviors", "behaviours"),
    ("behavioral", "behavioural"),
    ("behavior", "behaviour"),
    ("favorites", "favourites"),
    ("favorite", "favourite"),
    ("favored", "favoured"),
    ("favor", "favour"),
    ("colors", "colours"),
    ("colored", "coloured"),
    ("color", "colour"),
    ("centers", "centres"),
    ("centered", "centred"),
    ("center", "centre"),
    ("defenses", "defences"),
    ("defense", "defence"),
    ("offenses", "offences"),
    ("offense", "offence"),
    ("canceled", "cancelled"),
    ("canceling", "cancelling"),
    ("modeled", "modelled"),
    ("modeling", "modelling"),
    ("labeled", "labelled"),
    ("labeling", "labelling"),
    ("fulfill", "fulfil"),
    ("analyzed", "analysed"),
    ("analyzing", "analysing"),
    ("analyze", "analyse"),
)

_SPELLING_MAP = {american: british for american, british in _SPELLINGS}
_SPELLING_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word, _british in _SPELLINGS) + r")\b",
    re.IGNORECASE,
)


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def reply_ends_mid_sentence(text: str | None) -> bool:
    """True when a reply has words but no full stop, question mark, or exclamation mark."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    return re.search(r"[.?!]['\u2019\u201d\")\]]*$", stripped) is None


# "Let's try" is how a step asks for another attempt at its own work, such as
# more factual wording. Only opening a new activity counts.
_ACTIVITY_PATTERNS = (
    re.compile(r"\b(?:let'?s|let us)\s+(?:start|begin)\b", re.IGNORECASE),
    re.compile(r"\b(?:a|another|new|short|different)\s+exercise\b", re.IGNORECASE),
    re.compile(r"\bthis exercise will\b", re.IGNORECASE),
    re.compile(
        r"\b(?:we(?:'|’)ll|we will|let(?:'|’)s|i(?:'|’)ll|i will)\s+"
        r"(?:work on|use|practise|practice)\s+(?:a\s+|an\s+)?"
        r"(?:technique|exercise|practice|activity|strategy|skill|method)\b",
        re.IGNORECASE,
    ),
)

# The official close of a step. "Give it a try" is not this question.
_STEP_READY = re.compile(
    r"\bready (?:for|to) (?:the )?(?:next step|move on|continue|finish|see (?:your|the) summary)\b"
    r"|\bready to finish\b",
    re.IGNORECASE,
)

# A named technique is allowed only when the same idea is already in the step.
_TECHNIQUE_GROUPS = (
    ("reframe", "reframed", "reframing"),
    ("cognitive restructuring",),
    ("cognitive reappraisal",),
    (
        "shift perspective",
        "shift your perspective",
        "shifting perspective",
        "shifting your perspective",
    ),
)

_CALLED_ACTIVITY = re.compile(
    r"\b(?:technique|exercise|practice|activity|strategy|skill|method)\s+called\s+"
    r"[\"'\u201c\u2018]?"
    r"([A-Za-z][A-Za-z0-9'’\-]*(?:\s+[A-Za-z][A-Za-z0-9'’\-]*){0,4})",
    re.IGNORECASE,
)


def _contains_term(text: str, term: str) -> bool:
    return re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE) is not None


def _called_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw or "").strip(" \t\"'“”‘’.,;:!?")
    name = re.sub(r"^(?:the|a|an)\s+", "", name, flags=re.IGNORECASE)
    return name.strip()


def _unnamed_technique(text: str, allowed: str) -> bool:
    """True when the reply names a technique the step script does not."""
    allowed_lower = (allowed or "").lower()
    for group in _TECHNIQUE_GROUPS:
        if any(_contains_term(text, term) for term in group) and not any(
            _contains_term(allowed, term) for term in group
        ):
            return True
    for match in _CALLED_ACTIVITY.finditer(text or ""):
        name = _called_name(match.group(1))
        letters = re.sub(r"[^a-z]", "", name.lower())
        if len(letters) < 4:
            continue
        if name.lower() not in allowed_lower:
            return True
    return False


def stay_on_step_catalogue_text() -> str:
    """Live guard text: the retry hint, then the patterns that decide a retry."""
    from .turn_hint import STAY_ON_STEP_HINT

    lines = [
        STAY_ON_STEP_HINT,
        "",
        "The runner retries once with that hint, then holds the reply on the step.",
        "Activity patterns:",
    ]
    for pattern in _ACTIVITY_PATTERNS:
        lines.append(pattern.pattern)
    lines.append("Technique groups:")
    for group in _TECHNIQUE_GROUPS:
        lines.append(", ".join(group))
    return "\n".join(lines)


def reply_leaves_the_step(text: str | None, instructions: str | None) -> bool:
    """True when a reply starts an activity the live step does not name.

    A summary the user can confirm, and the question that asks if they are
    ready for the next step, are how a step finishes. They stay.
    """
    from .summary_confirmation import is_summary_confirmation

    raw = text or ""
    if is_summary_confirmation(raw):
        return False
    allowed = instructions or ""
    unnamed = _unnamed_technique(raw, allowed)
    if _STEP_READY.search(raw) and not unnamed:
        return False
    for pattern in _ACTIVITY_PATTERNS:
        if pattern.search(raw) and not pattern.search(allowed):
            return True
    # "A method called thought defusion" is a different activity.
    # "Reframe that thought" is not, unless the reply asks them to switch into it.
    if _called_name_missing(raw, allowed):
        return True
    if unnamed and re.search(r"\b(?:give it a try|ready to try)\b", raw, re.IGNORECASE):
        return True
    return False


def _called_name_missing(text: str, allowed: str) -> bool:
    allowed_lower = (allowed or "").lower()
    for match in _CALLED_ACTIVITY.finditer(text or ""):
        name = _called_name(match.group(1))
        letters = re.sub(r"[^a-z]", "", name.lower())
        if len(letters) < 4:
            continue
        if name.lower() not in allowed_lower:
            return True
    return False


_BANNED_OPENING = re.compile(
    r"^(?:thanks for sharing|thank you for sharing|thank you for|it sounds like)\b[^.?!]*[.?!]\s*",
    re.IGNORECASE,
)


def _strip_banned_openings(text: str) -> str:
    cleaned = text.strip()
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        cleaned = _BANNED_OPENING.sub("", cleaned, count=1).strip()
    return cleaned


def normalise_reply(text: str | None) -> str | None:
    if not text:
        return text
    for dash, replacement in _DASHES.items():
        text = text.replace(dash, replacement)

    def _spell(match: re.Match) -> str:
        word = match.group(0)
        replacement = _SPELLING_MAP[word.lower()]
        return _match_case(word, replacement)

    text = _SPELLING_PATTERN.sub(_spell, text)
    stripped = _strip_banned_openings(text)
    if stripped:
        text = stripped
    return re.sub(r"[ \t]{2,}", " ", text)
