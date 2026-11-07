"""Join Gemini text parts that were split at a word boundary.

pydantic-ai concatenates those parts with ``+=``, so "savings" + "for" becomes
"savingsfor". Structured calls through AI.ask merge the parts first. A part
that ends mid-word is also given a space: "sav" + "ings" becomes "sav ings".
"""

from __future__ import annotations

import re

_WORD_BREAK = re.compile(r"(?<=\w)\n(?=\w)")


def join_provider_pieces(pieces: list[str]) -> str:
    """Concatenate split text, putting back a space when both sides are alphanumeric."""
    text = ""
    for piece in pieces:
        if not piece:
            continue
        if text and _boundary_needs_space(text, piece):
            text += " "
        text += piece
    return repair_wrapped_words(text)


def repair_wrapped_words(value):
    """Turn a newline that sits between two words into a space."""
    if isinstance(value, str):
        return _WORD_BREAK.sub(" ", value)
    if isinstance(value, list):
        return [repair_wrapped_words(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_wrapped_words(item) for key, item in value.items()}
    return value


def merge_text_parts(parts: list) -> list:
    """Fold consecutive text parts into one, restoring spaces between them."""
    from pydantic_ai.messages import TextPart

    merged = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        merged.append(TextPart(content=join_provider_pieces(buffer)))
        buffer.clear()

    for part in parts:
        if isinstance(part, TextPart):
            buffer.append(part.content or "")
        else:
            flush()
            merged.append(part)
    flush()
    return merged


def _boundary_needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left[-1].isalnum() and right[0].isalnum()
