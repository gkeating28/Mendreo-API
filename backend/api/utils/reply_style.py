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
