"""Split markdown by heading. One token counter for chunking and the cap."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .constants import CHUNK_HARD_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS

_HEADING = re.compile(r"^(#{1,6})\s+(\S.*)$")


@dataclass(frozen=True)
class ChunkPiece:
    heading_path: str
    text: str
    token_count: int


def count_tokens(text: str) -> int:
    """Provisional count: one token per four characters.

    Chunking, the stored ``token_count``, and the 1,500-token cap all use
    this function. Replace it here when the spike picks a tokenizer.
    """
    if not text or not text.strip():
        return 0
    return max(1, (len(text) + 3) // 4)


def chunk_markdown(markdown: str) -> list[ChunkPiece]:
    pieces: list[ChunkPiece] = []
    for heading_path, body in _sections(markdown or ""):
        for window in _windows(body):
            token_count = count_tokens(window) + count_tokens(heading_path)
            if token_count <= 0:
                continue
            pieces.append(
                ChunkPiece(
                    heading_path=heading_path,
                    text=window,
                    token_count=token_count,
                )
            )
    return pieces


def take_within_budget(items, max_chunks: int, max_tokens: int, cost):
    """Keep a prefix of ``items``. Stop when the next one would exceed the cap.

    A later smaller item is not pulled forward in place of a larger one.
    """
    selected = []
    used = 0
    for item in items:
        if len(selected) >= max_chunks:
            break
        tokens = int(cost(item) or 0)
        if used + tokens > max_tokens:
            break
        selected.append(item)
        used += tokens
    return selected


def _sections(markdown: str) -> list[tuple[str, str]]:
    stack: list[tuple[int, str]] = []
    current: list[str] = []
    path = ""
    sections: list[tuple[str, str]] = []

    def flush():
        text = "\n".join(current).strip()
        if text:
            sections.append((path, text))

    for line in markdown.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            flush()
            current = []
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = " > ".join(title for _, title in stack)
            continue
        current.append(line)
    flush()
    if not sections and markdown.strip():
        sections.append(("", markdown.strip()))
    return sections


def _windows(text: str) -> list[str]:
    if count_tokens(text) <= CHUNK_TARGET_TOKENS:
        return [text]
    target_chars = CHUNK_TARGET_TOKENS * 4
    overlap_chars = CHUNK_OVERLAP_TOKENS * 4
    hard_chars = CHUNK_HARD_TOKENS * 4
    windows: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + target_chars)
        if end < length:
            snap = text.rfind("\n", start + 1, end)
            if snap <= start:
                snap = text.rfind(" ", start + 1, end)
            if snap > start:
                end = snap
        piece = text[start:end].strip()
        if piece:
            if len(piece) > hard_chars:
                piece = piece[:hard_chars].strip()
            if piece:
                windows.append(piece)
        if end >= length:
            break
        next_start = end - overlap_chars
        if next_start <= start:
            next_start = end
        start = next_start
    return windows
