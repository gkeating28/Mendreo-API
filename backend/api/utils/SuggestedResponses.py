import re
from typing import List, Optional

_INTERROGATIVE_CHIP_START = re.compile(
    r"^(?:"
    r"when|where|who|why|which|whose|whom|"
    r"what(?!\s+about\b)|"
    r"how(?!\s+about\b)"
    r")\b",
    re.IGNORECASE,
)
_AUXILIARY_YOU_CHIP_START = re.compile(
    r"^(?:can|could|would|should|do|does|did|is|are|was|were|will|may|might|shall)\s+you\b",
    re.IGNORECASE,
)
_CHIP_MAX_COUNT = 3


def _looks_like_question_chip(chip: str) -> bool:
    """True when a suggested reply is Toni's question restated, not a user answer."""
    text = (chip or "").strip()
    if not text:
        return True
    if _INTERROGATIVE_CHIP_START.search(text):
        return True
    if _AUXILIARY_YOU_CHIP_START.search(text):
        return True
    return False


def sanitize_suggested_responses(
    suggested_responses: Optional[List],
    agent_text: Optional[str] = None,
) -> Optional[List[str]]:
    """Keep tap-to-send answers; drop question restatements of `agent_text`."""
    if not suggested_responses:
        return suggested_responses

    agent_norm = re.sub(r"[^a-z0-9\s]", "", (agent_text or "").lower())
    cleaned: List[str] = []
    seen = set()
    for raw in suggested_responses:
        chip = str(raw).strip() if raw is not None else ""
        if not chip or chip in seen:
            continue
        if _looks_like_question_chip(chip):
            continue
        chip_norm = re.sub(r"[^a-z0-9\s]", "", chip.lower())
        chip_words = chip_norm.split()
        # Whole phrases copied from Toni's text, not a one-word answer that happens
        # to appear in the question ("Evenings" in "Would evenings work?").
        if (
            chip_norm
            and (len(chip_words) >= 3 or len(chip_norm) >= 16)
            and chip_norm in agent_norm
        ):
            continue
        seen.add(chip)
        cleaned.append(chip)
        if len(cleaned) >= _CHIP_MAX_COUNT:
            break

    return cleaned or None
