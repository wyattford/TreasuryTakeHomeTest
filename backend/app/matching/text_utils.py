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


# Typographic variants a label (or its transcription) may use for the same
# character; none of them changes the wording.
_TYPOGRAPHIC = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def normalize_statement(text: str) -> str:
    """For statements whose exact wording is prescribed: casefold, collapse
    whitespace and line breaks, and unify curly quotes and dashes, but keep
    every other punctuation mark. A missing colon or "(1)" is a real
    difference here, unlike in a brand name."""

    return _WHITESPACE_RE.sub(" ", text.translate(_TYPOGRAPHIC)).strip().casefold()


def similarity(a: str, b: str) -> float:
    """0.0-1.0 similarity ratio between normalized strings."""

    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


_ML_PER_UNIT: dict[str, float] = {
    "ml": 1.0,
    "cl": 10.0,
    "l": 1000.0,
    "fl oz": 29.5735,
    "pint": 473.176,
    "quart": 946.353,
    "gallon": 3785.41,
}

# Each alternative maps onto a key of _ML_PER_UNIT. Metric and US customary
# units are matched separately below: a label like "750 mL (25.4 FL OZ)"
# states the same volume twice, whereas "1 PINT 8 FL OZ" is one volume split
# across two units and has to be summed.
_METRIC_RE = re.compile(
    r"(\d+(?:,\d{3})+|\d+(?:[.,]\d+)?)\s*(ml|milliliters?|millilitres?|cl|centiliters?|centilitres?|l|liters?|litres?)\b", re.I
)
_US_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz\.?|fluid\s+ounces?|pints?|pts?\b|quarts?|qts?\b|gallons?|gal\b)", re.I)


_THOUSANDS_RE = re.compile(r"[1-9]\d{0,2}(?:,\d{3})+")


def _metric_number(raw: str) -> float:
    """A comma is a thousands separator in "1,000" and a decimal point in
    European "0,75" or "1,5"."""

    if _THOUSANDS_RE.fullmatch(raw):
        return float(raw.replace(",", ""))
    return float(raw.replace(",", "."))


def _metric_unit(raw: str) -> str:
    raw = raw.lower()
    if raw.startswith("m"):
        return "ml"
    if raw.startswith("c"):
        return "cl"
    return "l"


def _us_unit(raw: str) -> str:
    raw = raw.lower()
    if raw.startswith("f"):
        return "fl oz"
    if raw.startswith("p"):
        return "pint"
    if raw.startswith("q"):
        return "quart"
    return "gallon"


def parse_net_contents_ml(text: str) -> float | None:
    """Parses a net-contents string into milliliters: "750 mL", "75 cl",
    "1.75 L", "12 FL OZ", "1 PINT 8 FL OZ", "750 mL (25.4 FL OZ)". The metric
    statement wins when both are present. Returns None if nothing parses."""

    metric = _METRIC_RE.search(text)
    if metric:
        value = _metric_number(metric.group(1))
        return round(value * _ML_PER_UNIT[_metric_unit(metric.group(2))], 2)

    us_matches = list(_US_RE.finditer(text))
    if not us_matches:
        return None
    total = sum(float(m.group(1)) * _ML_PER_UNIT[_us_unit(m.group(2))] for m in us_matches)
    return round(total, 2)
