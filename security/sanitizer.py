"""Input sanitization, normalization, and safety guardrails (Requirement 4).

Features:
- Normalizes unicode whitespace and removes non-printable/control characters.
- Caps maximum input query length to mitigate token flooding attacks.
- Detects common prompt injection heuristics (e.g. system prompt overrides, role spoofing).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

# Common prompt injection and instruction override heuristic patterns
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"system\s+prompt\s+override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+developer\s+mode|dan|an\s+unrestricted\s+ai)", re.IGNORECASE),
    re.compile(r"disregard\s+all\s+safety\s+guidelines", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]", re.IGNORECASE),
    re.compile(r"reveal\s+your\s+(initial|system)\s+(prompt|instructions)", re.IGNORECASE),
    re.compile(r"(print|show|output|display|repeat|give|reveal)\s+(me\s+)?(your\s+)?(entire\s+|full\s+|complete\s+)?(system\s+prompt|instructions|rules|guidelines)", re.IGNORECASE),
    re.compile(r"(system\s+prompt|instructions)\s+verbatim", re.IGNORECASE),
]

MAX_QUERY_LENGTH = 1000


@dataclass
class SanitizationResult:
    """Result of sanitizing and validating a user input query."""

    original_query: str
    sanitized_query: str
    is_safe: bool = True
    flagged_reasons: Optional[List[str]] = None
    was_truncated: bool = False


def sanitize_query(raw_query: str) -> SanitizationResult:
    """Sanitize, normalize, and guardrail check an incoming user query.

    Args:
        raw_query: Raw user input text.

    Returns:
        SanitizationResult containing sanitized text, safety status, and flags.
    """
    if not isinstance(raw_query, str):
        raw_query = str(raw_query) if raw_query is not None else ""

    # 1. Unicode normalization (NFKC decomposes compatibility chars into canonical ones)
    normalized = unicodedata.normalize("NFKC", raw_query)

    # 2. Strip non-printable and ASCII control characters (preserve newline and tab)
    cleaned = "".join(ch for ch in normalized if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C"))

    # 3. Collapse multiple whitespaces and trim edges
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()

    # 4. Length capping
    was_truncated = False
    if len(cleaned) > MAX_QUERY_LENGTH:
        cleaned = cleaned[:MAX_QUERY_LENGTH].strip()
        was_truncated = True

    # 5. Check for prompt injection heuristic patterns
    flagged_reasons: List[str] = []
    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            flagged_reasons.append(f"Prompt injection pattern detected: '{pattern.pattern}'")

    is_safe = len(flagged_reasons) == 0

    return SanitizationResult(
        original_query=raw_query,
        sanitized_query=cleaned,
        is_safe=is_safe,
        flagged_reasons=flagged_reasons if flagged_reasons else None,
        was_truncated=was_truncated,
    )

