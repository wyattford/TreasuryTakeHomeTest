"""Combines the separate front- and back-label extractions into the single
set of label fields the matching engine compares, recording which side each
value came from (needed for placement rules like wine's brand-label
requirement)."""

from __future__ import annotations

from app.matching.text_utils import normalize
from app.schemas import ExtractedLabelFields

_LIST_FIELDS = {"other_disclosures", "illegible_fields"}
# Fields where the back label's reading wins instead of the front's: the
# statements that normally live on the back. Shown a front label without
# them, the model tends to fill them in anyway — a fragment or invented
# Government Warning, or the brand name repeated as the bottler's name and
# address. Preferring the back also means an invented, perfectly-worded front
# "warning" can never mask a real wording violation printed on the back.
_BACK_WINS = {"government_warning_text", "name_address"}
_SCALAR_FIELDS = [name for name in ExtractedLabelFields.model_fields if name not in _LIST_FIELDS]


def merge_extractions(
    front: ExtractedLabelFields, back: ExtractedLabelFields | None
) -> tuple[ExtractedLabelFields, dict[str, str]]:
    """Front-label values win (except for the fields in _BACK_WINS); the
    other label fills in whatever the preferred one doesn't carry. Returns the merged
    fields and a field -> "front"/"back" map for every field that has a value."""

    sides = [("front", front)] + ([("back", back)] if back is not None else [])

    merged: dict[str, object] = {}
    sources: dict[str, str] = {}
    for name in _SCALAR_FIELDS:
        for side, fields in reversed(sides) if name in _BACK_WINS else sides:
            value = getattr(fields, name)
            if value is not None:
                merged[name] = value
                sources[name] = side
                break

    disclosures: list[str] = []
    seen: set[str] = set()
    for _, fields in sides:
        for disclosure in fields.other_disclosures:
            if normalize(disclosure) not in seen:
                seen.add(normalize(disclosure))
                disclosures.append(disclosure)
    merged["other_disclosures"] = disclosures

    # A field only counts as illegible if nothing usable was read for it on
    # either side. A back label reporting the brand name "illegible" doesn't
    # matter when the front label printed it clearly — and the model also
    # sometimes marks a field illegible while transcribing it correctly.
    illegible: list[str] = []
    for _, fields in sides:
        for name in fields.illegible_fields:
            if merged.get(name) is None and name not in illegible:
                illegible.append(name)
    merged["illegible_fields"] = illegible

    return ExtractedLabelFields(**merged), sources
