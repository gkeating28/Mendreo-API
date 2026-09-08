import re
from typing import List, Optional

_COMPLETION_RESULT_MAX_LEN = 400

_PLACEHOLDER_COMPLETION = re.compile(
    r"^(n/?a\.?|n\.a\.|na|none|null|nil|-|unknown|not sure|nothing)$",
    re.IGNORECASE,
)
_STEP_COMPLETED_PLACEHOLDER = re.compile(
    r"^step\s+\d+(\s+of\s+\d+)?\s+completed\.?$",
    re.IGNORECASE,
)
_FACILITATOR_COMPLETION = re.compile(
    r"user ready for step|"
    r"ready for step\s+\d+|"
    r"user provided|"
    r"\bthe user\b|"
    r"\bhelp the user\b|"
    r"^user\b",
    re.IGNORECASE | re.DOTALL,
)
_PROCEED_CONFIRMATION = re.compile(
    r"^(y|yes|yeah|yep|yup|ok|okay|k|sure|ready|continue|next|"
    r"let'?s go|lets go|go ahead|please|do it|i('?m| am) ready|"
    r"sounds good|alright|all right)[\s!.]*$",
    re.IGNORECASE,
)
_QA_COMMAND_TEXTS = {
    "qa skip step",
    "qa asset image",
    "qa asset post",
    "qa asset file",
    "qa exercise",
}


def is_usable_completion_result(value: Optional[str]) -> bool:
    """True when the model (or a user turn) is a real captured answer, not a placeholder."""
    text = (value or "").strip()
    if not text:
        return False
    if text.lower() in _QA_COMMAND_TEXTS:
        return False
    if _PLACEHOLDER_COMPLETION.match(text):
        return False
    if _STEP_COMPLETED_PLACEHOLDER.match(text):
        return False
    if _FACILITATOR_COMPLETION.search(text):
        return False
    if _PROCEED_CONFIRMATION.match(text):
        return False
    return True


def pick_completion_result_from_texts(texts: List[str]) -> Optional[str]:
    """Newest-first: first substantial user utterance, skipping yes/ok and placeholders."""
    for raw in texts:
        text = (raw or "").strip()
        if not is_usable_completion_result(text):
            continue
        if len(text) > _COMPLETION_RESULT_MAX_LEN:
            text = text[: _COMPLETION_RESULT_MAX_LEN - 3].rstrip() + "..."
        return text
    return None
