"""Keep stored facts to words the user actually said."""

from __future__ import annotations

import re

USER_FACT_RULE = (
    "Use only what the user said in their own messages. "
    "Ignore any statement about the user made in an assistant message "
    "unless the user confirmed it."
)

_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "because",
        "been",
        "being",
        "from",
        "have",
        "having",
        "into",
        "just",
        "like",
        "more",
        "only",
        "said",
        "says",
        "that",
        "their",
        "them",
        "then",
        "they",
        "this",
        "very",
        "what",
        "when",
        "with",
        "would",
        "your",
    }
)


def user_text_from_messages(messages) -> str:
    parts = []
    for message in messages:
        sender = getattr(message, "sender", None)
        if sender is not None and getattr(sender, "consumer_id", None):
            text = (getattr(message, "text", None) or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def ground_extracted_value(value: str | None, user_text: str) -> str | None:
    """Return the value when the user's words support it, otherwise nothing."""
    text = (value or "").strip()
    if not text:
        return None
    if grounded_in_user_words(text, user_text):
        return text
    return None


def grounded_in_user_words(statement: str, user_text: str) -> bool:
    """True when the statement repeats the user, or enough of its words do."""
    statement = (statement or "").strip()
    if not statement:
        return True
    user = (user_text or "").casefold()
    if statement.casefold() in user:
        return True
    words = _content_words(statement)
    if not words:
        return True
    hits = sum(1 for word in words if _in_user(word, user))
    needed = 1 if len(words) == 1 else max(1, (len(words) + 1) // 2)
    return hits >= needed


def keep_grounded_prose(text: str | None, user_text: str) -> str:
    """Drop sentences the user never said. An empty result means keep the previous text."""
    raw = (text or "").strip()
    if not raw:
        return ""
    sentences = [part.strip() for part in _SENTENCE.findall(raw) if part.strip()]
    if not sentences:
        sentences = [raw]
    kept = [sentence for sentence in sentences if grounded_in_user_words(sentence, user_text)]
    return " ".join(kept).strip()


def _content_words(text: str) -> list[str]:
    return [
        word
        for word in _WORD.findall((text or "").casefold())
        if len(word) >= 4 and word not in _STOP
    ]


def _in_user(word: str, user: str) -> bool:
    if word in user:
        return True
    return len(word) >= 5 and word[:5] in user
