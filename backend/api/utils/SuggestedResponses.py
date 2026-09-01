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
_MCQ_MAX_COUNT = 6
_NUMBERED_SPLIT = re.compile(r"(?<!\d)(\d+)\s*[\)\.]\s+")
_CHOICE_LEAD = re.compile(
    r"(?:"
    r"influenced\s+by|"
    r"could\s+(?:it|this|that)\s+be(?:\s+influenced\s+by)?|"
    r"(?:feel|sound|look)\s+like|"
    r"which\s+(?:one\s+)?of(?:\s+these)?|"
    r"(?:an\s+)?example\s+of|"
    r"more\s+like"
    r")\s*[:,]?\s+",
    re.IGNORECASE,
)
_QUOTED = re.compile(
    r"(?<![A-Za-z])[\"'‘’“”]([^\"'‘’“”]{1,80})[\"'‘’“”](?![A-Za-z])"
)
_LIST_MARKER = re.compile(
    r"^(?:\(?[A-Za-z]\)|[A-Za-z][.)]|\d+[.)])\s+"
)
_ALL_OR_NOTHING = re.compile(r"\ball\s+or\s+nothing\b", re.IGNORECASE)
_NEITHER = re.compile(
    r"\bor\s+(neither(?:\s+of\s+(?:these|them|those))?|"
    r"none(?:\s+of\s+(?:these|them|those))?)\b",
    re.IGNORECASE,
)
_AGENT_VOICE = re.compile(
    r"^(?:let'?s|lets|let us|we'?ll|we will|i want you|look at|try to|consider|challenge)\b",
    re.IGNORECASE,
)
_POLAR_QUESTION = re.compile(
    r"^(?:do|does|did|are|is|was|were|can|could|would|will|have|has|had)\s+"
    r"(?:you|this|that|it)\b",
    re.IGNORECASE,
)
_POLAR_CHIPS = ["Yes", "No", "Not sure"]


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


def _trim_choice(raw: str) -> str:
    body = re.sub(r"^(?:or\s+)", "", (raw or "").strip(), flags=re.IGNORECASE)
    body = _LIST_MARKER.sub("", body, count=1)
    body = re.sub(r"[\s,;]+(?:or)?\s*$", "", body, flags=re.IGNORECASE)
    return body.strip().rstrip("?.!").strip()


def _chip_label(raw: str) -> str:
    text = _trim_choice(raw)
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _space_norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", value.lower())).strip()


def _is_plausible_choice(label: str) -> bool:
    if not label or label.endswith((":", ";")):
        return False
    if _AGENT_VOICE.search(label):
        return False
    words = label.split()
    if len(words) == 1 and re.match(r"^(we|i|you|it|they)$", label, re.IGNORECASE):
        return False
    if re.match(r"^[A-Za-z]$", label):
        return True
    if re.match(r"^[A-Za-z]\s", label):
        return False
    if len(words) > 8 or re.search(r"[.?]", label):
        return False
    return True


def _copied_from_agent(chip: str, agent_text: Optional[str]) -> bool:
    if not agent_text:
        return False
    chip_space = _space_norm(chip)
    agent_space = _space_norm(agent_text)
    if not chip_space:
        return False
    words = chip_space.split()
    if (len(words) >= 3 or len(chip_space) >= 16) and chip_space in agent_space:
        return True
    if len(words) >= 4:
        for i in range(len(words) - 3):
            if " ".join(words[i : i + 4]) in agent_space:
                return True
    return False


def _keep_user_chips(
    chips: List[str],
    agent_text: Optional[str] = None,
    allow_in_prompt: bool = False,
) -> List[str]:
    unique: List[str] = []
    seen = set()
    for raw in chips:
        label = _chip_label(raw)
        if not _is_plausible_choice(label):
            continue
        if not allow_in_prompt and _copied_from_agent(label, agent_text):
            continue
        key = _norm(label)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(label)
    return unique


def _last_neither(clause: str) -> str:
    last = ""
    for match in _NEITHER.finditer(clause):
        last = _chip_label(match.group(1))
    return last


def _choice_clause(text: str) -> Optional[str]:
    leads = list(_CHOICE_LEAD.finditer(text))
    if leads:
        return text[leads[-1].end() :]
    if not _NEITHER.search(text):
        return None
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    for chunk in reversed(chunks):
        if _NEITHER.search(chunk):
            return chunk
    return text


def _split_or_labels(part: str) -> List[str]:
    if _ALL_OR_NOTHING.search(part):
        return [part]
    bits = [bit.strip() for bit in re.split(r"\s+or\s+", part, flags=re.IGNORECASE) if bit.strip()]
    if len(bits) >= 2 and all(len(bit.split()) == 1 and len(bit) <= 24 for bit in bits):
        return bits
    return [part]


def extract_inline_choices(text: Optional[str]) -> List[str]:
    """
    Pull tap targets from quoted / 'A, B, or neither' lists in the prompt.

    Handles copy like: feel influenced by 'all or nothing thinking,'
    'jumping to conclusions,' or neither of these?
    """
    if not text:
        return []

    clause = _choice_clause(text)
    if not clause:
        return []

    neither = _last_neither(clause)
    body = _NEITHER.sub(" ", clause) if neither else clause
    body = re.sub(r"\s+", " ", body).strip()

    quoted = []
    for match in _QUOTED.finditer(clause):
        label = _chip_label(match.group(1))
        if _is_plausible_choice(label):
            quoted.append(label)

    options: List[str] = list(quoted) if len(quoted) >= 2 else []
    if len(options) < 2:
        unquoted = _QUOTED.sub(lambda m: m.group(1), body)
        comma_parts = [
            re.sub(r"^(?:or\s+)", "", part.strip(), flags=re.IGNORECASE)
            for part in unquoted.split(",")
            if part.strip()
        ]
        pieces: List[str] = []
        if len(comma_parts) >= 2:
            for part in comma_parts:
                pieces.extend(_split_or_labels(part))
        else:
            pieces.extend(_split_or_labels(unquoted.strip()))
        for part in pieces:
            label = _chip_label(part)
            if _is_plausible_choice(label):
                options.append(label)

    if neither and all(_norm(option) != _norm(neither) for option in options):
        options.append(neither)

    unique = _keep_user_chips(options, None, True)
    return unique[:_MCQ_MAX_COUNT] if len(unique) >= 2 else []


def extract_numbered_options(text: Optional[str]) -> List[str]:
    """
    Pull tap targets out of '1) Foo, 2) Bar, or 3) Baz' (and 1. / newline lists).

    Used when Toni enumerates choices in the prompt — those labels are the chips,
    even if they also appear in the question text.
    """
    if not text:
        return []
    parts = _NUMBERED_SPLIT.split(text.strip())
    if len(parts) < 5:
        return []
    options: List[str] = []
    numbers: List[str] = []
    i = 1
    while i + 1 < len(parts):
        numbers.append(parts[i])
        body = parts[i + 1].strip()
        body = re.sub(r"^(?:or\s+)", "", body, flags=re.IGNORECASE)
        body = re.sub(r"[\s,;]+(?:or)?\s*$", "", body, flags=re.IGNORECASE)
        body = body.strip(" \t\n\r")
        body = body.rstrip("?.!")
        if body:
            options.append(body)
        i += 2
    if len(options) < 2 or numbers[0] != "1":
        return []
    usable = _keep_user_chips(options, None, True)
    return usable[:_MCQ_MAX_COUNT] if len(usable) >= 2 else []


def extract_polar_options(text: Optional[str]) -> List[str]:
    """Yes / No / Not sure when the last sentence is a polar question."""
    if not text:
        return []
    chunks = re.split(r"(?<=[.!])\s+", text.strip())
    last = (chunks[-1] if chunks else text).strip()
    if not last.endswith("?"):
        return []
    if re.search(r",\s+or\s+", last, re.IGNORECASE):
        return []
    if _POLAR_QUESTION.search(last):
        return list(_POLAR_CHIPS)
    return []


_CLOSING_CHIPS = ["I have a question", "I'm ready to finish"]
_START_CHIP = re.compile(
    r"^(?:i(?:'?m| am) )?ready to start(?:\s+(?:the|this)\s+exercise)?$"
    r"|^(?:let'?s|lets) start(?: now)?$"
    r"|^start(?: the| this)? exercise$",
    re.IGNORECASE,
)
_NARRATIVE_ASK = re.compile(
    r"\btell me\b|"
    r"\bplease (?:tell|share|describe)\b|"
    r"\bspecifically what\b|"
    r"\bwhat (?:are you|you are|you're) (?:worried|feeling|thinking|experiencing)\b|"
    r"\bwhat (?:can|could|should) we do\b|"
    r"\bfigure out what to do\b|"
    r"\bwhat to do about (?:it|this|that)\b",
    re.IGNORECASE,
)
_START_INVITE = re.compile(
    r"would you like to (?:start|begin|try)|"
    r"tap (?:below )?to start|"
    r"\b(?:start|begin) this exercise\b|"
    r"\bready to (?:start|begin)(?:\s+(?:the|this)\s+exercise)\b",
    re.IGNORECASE,
)
_CONTINUE_CHIP = re.compile(
    r"^(?:yes[,.]?\s+)?(?:i(?:'?m| am) )?ready to continue(?:\s+to (?:the )?next step)?$"
    r"|^(?:yes[,.]?\s+)?(?:let'?s )?continue$"
    r"|^continue to (?:the )?next step$",
    re.IGNORECASE,
)
_CONTINUE_INVITE = re.compile(
    r"shall we move on|should we move on|ready to proceed|ready to continue|"
    r"shall we (?:continue|proceed)|continue to (?:the )?next(?: step)?",
    re.IGNORECASE,
)


def _last_sentence(text: str) -> str:
    chunks = re.split(r"(?<=[.!?])\s+", text.strip())
    return (chunks[-1] if chunks else text).strip()


def is_narrative_ask(text: Optional[str]) -> bool:
    if not text:
        return False
    return bool(_NARRATIVE_ASK.search(_last_sentence(text)))


def extract_closing_options(text: Optional[str]) -> List[str]:
    """Wrap-up questions should offer finish vs more questions, not Yes/No."""
    if not text:
        return []
    chunks = re.split(r"(?<=[.!])\s+", text.strip())
    last = (chunks[-1] if chunks else text).strip()
    if not last.endswith("?"):
        return []
    lowered = last.lower()
    if re.search(r"\b(end|finish|stop|leave|close)\s+(the\s+)?exercise\b", lowered):
        return list(_CLOSING_CHIPS)
    if re.search(r"\bready to (end|finish|stop)\b", lowered):
        return list(_CLOSING_CHIPS)
    return []


def sanitize_suggested_responses(
    suggested_responses: Optional[List],
    agent_text: Optional[str] = None,
) -> Optional[List[str]]:
    """Keep tap-to-send answers; drop question restatements of `agent_text`."""
    listed = extract_numbered_options(agent_text) or extract_inline_choices(agent_text)
    if listed:
        return listed[:_MCQ_MAX_COUNT]

    closing = extract_closing_options(agent_text)
    if closing:
        return closing

    if is_narrative_ask(agent_text):
        return None

    cleaned: List[str] = []
    if suggested_responses:
        usable = [
            str(raw).strip()
            for raw in suggested_responses
            if raw is not None
            and str(raw).strip()
            and not _looks_like_question_chip(str(raw).strip())
        ]
        cleaned = _keep_user_chips(usable, agent_text, False)
        if not _START_INVITE.search(agent_text or ""):
            cleaned = [chip for chip in cleaned if not _START_CHIP.search(chip)]
        if not _CONTINUE_INVITE.search(agent_text or ""):
            cleaned = [chip for chip in cleaned if not _CONTINUE_CHIP.search(chip)]
        if cleaned:
            return cleaned[:_CHIP_MAX_COUNT]

    polar = extract_polar_options(agent_text)
    if polar:
        return polar
    if not suggested_responses:
        return suggested_responses
    return None
