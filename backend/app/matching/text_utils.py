"""Small text-normalization helpers shared by the matching engine.

Kept separate and dependency-free (stdlib only: re, difflib) so they're easy
to unit test on their own against the specific examples from the stakeholder
interviews (e.g. "STONE'S THROW" vs "Stone's Throw" should match).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")

# Below this similarity ratio on normalized text, treat two fuzzy-matched
# strings as a mismatch rather than a borderline flag.
FUZZY_MATCH_THRESHOLD = 0.90


def normalize(text: str) -> str:
    """Casefold, strip punctuation, and collapse whitespace — e.g.
    "STONE'S THROW" and "Stone's Throw" both normalize to "stones throw"."""

    text = text.casefold()
    text = _PUNCTUATION_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def similarity(a: str, b: str) -> float:
    """0.0-1.0 similarity ratio between normalized strings."""

    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


_NET_CONTENTS_RE = re.compile(r"([\d.]+)\s*(ml|milliliters?|l|liters?|litres?)\b", re.IGNORECASE)


def parse_net_contents_ml(text: str) -> float | None:
    """Parses a net-contents string like "750 mL" or "1.75 L" into
    milliliters. Returns None if it can't be parsed."""

    match = _NET_CONTENTS_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("l"):
        value *= 1000
    return value
