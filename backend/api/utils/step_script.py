"""Follow the current step's instructions in the order they are written.

The instructions are the Unified Protocol for this session. Nothing here is
specific to one exercise.
"""

from __future__ import annotations

import re

_TAGS = re.compile(r"<[^>]+>")
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z']{4,}")
_STOP = {
    "about",
    "after",
    "again",
    "also",
    "ask",
    "asked",
    "asks",
    "from",
    "have",
    "help",
    "into",
    "just",
    "make",
    "more",
    "must",
    "only",
    "that",
    "them",
    "then",
    "they",
    "this",
    "user",
    "what",
    "when",
    "with",
    "your",
}


def instruction_items(instructions: str) -> list[str]:
    """Ordered sentences from a step's instructions."""
    text = _TAGS.sub(" ", instructions or "")
    items = []
    for chunk in _SPLIT.split(text):
        cleaned = " ".join(chunk.split()).strip(" -*")
        if len(_content_words(cleaned)) >= 1 and len(cleaned.split()) >= 4:
            items.append(cleaned)
    return items


def _content_words(text: str) -> set[str]:
    return {
        word
        for word in _WORD.findall((text or "").lower())
        if word not in _STOP
    }


def _shares(left: set[str], right: set[str]) -> int:
    count = 0
    for word in left:
        for other in right:
            if word == other or word.startswith(other) or other.startswith(word):
                count += 1
                break
    return count


def _covered(item: str, assistant_texts: list[str]) -> bool:
    words = _content_words(item)
    if not words:
        return False
    needed = 1 if len(words) < 3 else 2
    for message in assistant_texts:
        if _shares(words, _content_words(message)) >= needed:
            return True
    return False


def next_instruction(instructions: str, assistant_texts: list[str] | None = None) -> str | None:
    """The first instruction sentence this conversation has not already asked."""
    asked = list(assistant_texts or [])
    for item in instruction_items(instructions):
        if not _covered(item, asked):
            return item
    return None


def sequence_hint(instructions: str, assistant_texts: list[str] | None = None) -> str | None:
    nxt = next_instruction(instructions, assistant_texts)
    if not nxt:
        return None
    return (
        "This exercise is the Unified Protocol for this session. "
        "Follow this step's instructions in the order they are written. "
        f"The next part is: {nxt} "
        "Do only that. Do not add any technique or activity those instructions do not name."
    )


def stay_on_script_hint(instructions: str, assistant_texts: list[str] | None = None) -> str:
    """Retry hint after a reply left the written instructions."""
    nxt = next_instruction(instructions, assistant_texts)
    if not nxt:
        return (
            "That reply did not follow this step's instructions. "
            "Do the next part of those instructions and nothing else. "
            "Do not add any technique or activity they do not name."
        )
    return (
        "That reply did not follow this step's instructions. "
        f"The next part, and the only part for this turn, is: {nxt} "
        "Do not add any technique or activity those instructions do not name."
    )
