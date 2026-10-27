"""Reject Unified Protocol case material before it can be indexed."""

from __future__ import annotations

import re

_DIALOGUE = re.compile(r"(?m)^\s*[TP]\s*:")
_CASE = re.compile(r"case\s+vignette|case\s+example", re.IGNORECASE)
_AGE = re.compile(r"\b\d{1,2}-year-old\b", re.IGNORECASE)
_REPORTED = re.compile(
    r"\b[A-Z][a-z]{2,}\s+(?:reported|presented|complained)\b"
)
_VIGNETTE_NAMES = re.compile(r"\b(?:Amira|Kevin|Marco|Rachel)\b")


def case_material_reason(heading_path: str, text: str) -> str | None:
    """Why this chunk is case material, or None when it may be indexed."""
    blob = f"{heading_path or ''}\n{text or ''}"
    if _DIALOGUE.search(blob):
        return "session dialogue"
    if _CASE.search(blob):
        return "case vignette"
    if _AGE.search(blob) or _REPORTED.search(blob) or _VIGNETTE_NAMES.search(blob):
        return "named patient story"
    return None


def case_material_block(pieces) -> str | None:
    """One message listing every distinct reason found in these chunks."""
    reasons = []
    for piece in pieces:
        heading = getattr(piece, "heading_path", "") if not isinstance(piece, tuple) else piece[0]
        text = getattr(piece, "text", "") if not isinstance(piece, tuple) else piece[1]
        reason = case_material_reason(heading, text)
        if reason and reason not in reasons:
            reasons.append(reason)
    if not reasons:
        return None
    return (
        "This source contains case material and cannot be submitted: "
        + "; ".join(reasons)
        + "."
    )
