"""Compares an application's declared fields against a label's extracted
fields and produces one verdict per field.

Philosophy: legally-exact rules are decided deterministically in code, never
left to the vision model's own judgment. The model's job is extraction; this
module's job is the compliance decision.

Every declared value is optional. When the application declares a field, the
label is checked against it; when it doesn't, the label is still checked on
its own terms (is a required field printed at all, is the container a
standard size, is the Government Warning exact).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.ttb_rules import (
    ABV_TOLERANCE_PERCENTAGE_POINTS,
    GOVERNMENT_WARNING_TEXT,
    NET_CONTENTS_TOLERANCE_ML,
    PROOF_TOLERANCE,
    WINE_BRAND_LABEL_FIELDS,
    BeverageClass,
    is_standard_fill,
    required_fields_for,
)
from app.matching.text_utils import (
    FUZZY_MATCH_THRESHOLD,
    normalize,
    normalize_statement,
    parse_net_contents_ml,
    similarity,
)
from app.schemas import ApplicationIn, ExtractedLabelFields

MATCH = "match"
MISMATCH = "mismatch"
FLAGGED = "flagged"
MISSING = "missing"


@dataclass
class Verdict:
    field_name: str
    application_value: str | None
    extracted_value: str | None
    match_type: str  # exact | tolerance | enum | fuzzy | presence
    status: str  # match | mismatch | flagged | missing
    detail: str | None = None


# Extraction schema field name -> verdict field name, where they differ, so an
# "illegible" flag names the same field the rest of the results use.
_VERDICT_FIELD_NAMES = {"abv_percent": "abv", "government_warning_text": "government_warning"}

_NOT_DECLARED_FOUND = "Found on the label. Nothing was declared on the application to compare it against."
_NOT_DECLARED_MISSING = "Required on the label, but not found."
_POSSIBLY_UNREADABLE = "It may be printed but unreadable (blur, glare, or angle) — please check the label by eye."


def _undeclared_verdict(field_name: str, extracted: str | None, *, required: bool) -> Verdict:
    """Label-only check for a field the application left blank."""

    if extracted:
        return Verdict(field_name, None, extracted, "presence", MATCH, _NOT_DECLARED_FOUND)
    if required:
        return Verdict(field_name, None, None, "presence", MISSING, _NOT_DECLARED_MISSING)
    return Verdict(field_name, None, None, "presence", MATCH, "Not required for this label; not present.")


def _fuzzy_verdict(field_name: str, declared: str | None, extracted: str | None) -> Verdict:
    if not declared:
        return _undeclared_verdict(field_name, extracted, required=True)
    if not extracted:
        return Verdict(field_name, declared, extracted, "fuzzy", MISSING, "Not found on the label.")
    ratio = similarity(declared, extracted)
    if normalize(declared) == normalize(extracted):
        return Verdict(field_name, declared, extracted, "fuzzy", MATCH)
    if ratio >= FUZZY_MATCH_THRESHOLD:
        detail = f"Close but not identical ({ratio:.0%} similar) — worth a human glance."
        return Verdict(field_name, declared, extracted, "fuzzy", FLAGGED, detail)
    return Verdict(field_name, declared, extracted, "fuzzy", MISMATCH, f"Only {ratio:.0%} similar.")


def _abv_verdict(declared: float | None, extracted: float | None, *, required: bool) -> Verdict:
    field_name = "abv"
    if declared is None and extracted is None:
        if required:
            return Verdict(field_name, None, None, "tolerance", MISSING, _NOT_DECLARED_MISSING)
        return Verdict(field_name, None, None, "tolerance", MATCH, "Not required for this label; not present.")
    if declared is None:
        return Verdict(field_name, None, _fmt(extracted), "presence", MATCH, _NOT_DECLARED_FOUND)
    if extracted is None:
        return Verdict(field_name, _fmt(declared), None, "tolerance", MISSING, "Not found on the label.")
    diff = abs(declared - extracted)
    if diff <= ABV_TOLERANCE_PERCENTAGE_POINTS:
        return Verdict(field_name, _fmt(declared), _fmt(extracted), "tolerance", MATCH)
    return Verdict(
        field_name,
        _fmt(declared),
        _fmt(extracted),
        "tolerance",
        MISMATCH,
        f"Differs by {diff:.2f} points, outside the ±{ABV_TOLERANCE_PERCENTAGE_POINTS} tolerance in 27 CFR 5.65.",
    )


def _net_contents_verdict(declared: str | None, extracted: str | None, beverage_class: BeverageClass) -> Verdict:
    field_name = "net_contents"
    if not extracted:
        return Verdict(field_name, declared, None, "enum", MISSING, "Not found on the label.")
    extracted_ml = parse_net_contents_ml(extracted)
    if extracted_ml is None:
        detail = "Couldn't read a container size from the label text."
        return Verdict(field_name, declared, extracted, "enum", FLAGGED, detail)
    if not is_standard_fill(beverage_class, extracted_ml):
        citation = "27 CFR 4.72" if beverage_class == BeverageClass.WINE else "27 CFR 5.203"
        detail = f"{extracted_ml:g} mL is not one of the authorized container sizes for this product ({citation})."
        return Verdict(field_name, declared, extracted, "enum", FLAGGED, detail)
    if not declared:
        return Verdict(field_name, None, extracted, "enum", MATCH, _NOT_DECLARED_FOUND)
    declared_ml = parse_net_contents_ml(declared)
    if declared_ml is None:
        detail = "Couldn't understand the declared net contents, so it can't be checked against the label."
        return Verdict(field_name, declared, extracted, "enum", FLAGGED, detail)
    if abs(declared_ml - extracted_ml) > NET_CONTENTS_TOLERANCE_ML:
        detail = f"Label shows {extracted_ml:g} mL but the application declares {declared_ml:g} mL."
        return Verdict(field_name, declared, extracted, "enum", MISMATCH, detail)
    return Verdict(field_name, declared, extracted, "enum", MATCH)


def _proof_verdict(proof: float, abv: float | None) -> Verdict:
    """Proof is twice the ABV by definition; a label stating both must agree
    with itself."""

    field_name = "proof"
    if abv is None:
        detail = "The label states proof but no alcohol content to check it against."
        return Verdict(field_name, None, f"{proof:g} proof", "tolerance", FLAGGED, detail)
    if abs(proof - 2 * abv) <= PROOF_TOLERANCE:
        return Verdict(field_name, None, f"{proof:g} proof", "tolerance", MATCH, f"Consistent with {abv:g}% alcohol.")
    detail = f"{proof:g} proof means {proof / 2:g}% alcohol, but the label says {abv:g}%."
    return Verdict(field_name, None, f"{proof:g} proof", "tolerance", MISMATCH, detail)


def _apply_wine_brand_label_rule(verdicts: list[Verdict], field_sources: dict[str, str]) -> None:
    """27 CFR 4.32(a): a wine's brand name and class/type must be on the brand
    (front) label. A value only found on the back label is flagged even if it
    otherwise matches."""

    for verdict in verdicts:
        if verdict.field_name in WINE_BRAND_LABEL_FIELDS and field_sources.get(verdict.field_name) == "back":
            note = "Only found on the back label — on wine, this must appear on the brand (front) label (27 CFR 4.32(a))."
            verdict.detail = f"{verdict.detail} {note}" if verdict.detail else note
            if verdict.status == MATCH:
                verdict.status = FLAGGED
                verdict.match_type = "placement"


def _warning_verdict(extracted_text: str | None) -> Verdict:
    field_name = "government_warning"
    if not extracted_text:
        detail = "No Government Warning statement found on the label."
        return Verdict(field_name, GOVERNMENT_WARNING_TEXT, None, "exact", MISSING, detail)
    if "GOVERNMENT WARNING" not in extracted_text:
        return Verdict(
            field_name,
            GOVERNMENT_WARNING_TEXT,
            extracted_text,
            "exact",
            MISMATCH,
            '"GOVERNMENT WARNING" must appear in capital letters (27 CFR 16.21).',
        )
    if normalize_statement(extracted_text) == normalize_statement(GOVERNMENT_WARNING_TEXT):
        return Verdict(field_name, GOVERNMENT_WARNING_TEXT, extracted_text, "exact", MATCH)
    return Verdict(
        field_name,
        GOVERNMENT_WARNING_TEXT,
        extracted_text,
        "exact",
        MISMATCH,
        "Wording or punctuation does not match the statement prescribed verbatim by 27 CFR 16.21.",
    )


def _presence_verdict(field_name: str, declared: str | None, extracted: str | None, required: bool) -> Verdict:
    if extracted:
        matched = declared is None or normalize(declared) in normalize(extracted) or normalize(extracted) in normalize(declared)
        status = MATCH if (declared is None or matched) else FLAGGED
        detail = None if status == MATCH else "Present on the label, but doesn't clearly match the declared value."
        return Verdict(field_name, declared, extracted, "presence", status, detail)
    if required:
        return Verdict(field_name, declared, extracted, "presence", MISSING, "Required but not found on the label.")
    return Verdict(field_name, declared, extracted, "presence", MATCH, "Not required for this label; not present.")


def _fmt(value: float | None) -> str | None:
    return None if value is None else f"{value:g}%"


def compare(
    application: ApplicationIn, extracted: ExtractedLabelFields, field_sources: dict[str, str] | None = None
) -> list[Verdict]:
    """``field_sources`` maps extracted field names to the image ("front" /
    "back") each was read from; placement rules are only checked when it's
    provided."""

    beverage_class = BeverageClass(application.beverage_class)
    required = required_fields_for(beverage_class, application.imported)

    verdicts: list[Verdict] = [
        _fuzzy_verdict("brand_name", application.brand_name, extracted.brand_name),
        _fuzzy_verdict("class_type", application.class_type, extracted.class_type),
        _abv_verdict(application.abv, extracted.abv_percent, required="abv" in required),
        _net_contents_verdict(application.net_contents, extracted.net_contents, beverage_class),
        _fuzzy_verdict("name_address", application.name_address, extracted.name_address),
        _warning_verdict(extracted.government_warning_text),
    ]

    if extracted.proof is not None:
        verdicts.append(_proof_verdict(extracted.proof, extracted.abv_percent))

    if application.imported or "country_of_origin" in required or application.country_of_origin:
        verdicts.append(
            _presence_verdict(
                "country_of_origin",
                application.country_of_origin,
                extracted.country_of_origin,
                required="country_of_origin" in required,
            )
        )

    if beverage_class == BeverageClass.WINE:
        verdicts.append(_presence_verdict("appellation", application.appellation, extracted.appellation, required=False))
        verdicts.append(
            _presence_verdict(
                "sulfite_declaration",
                application.sulfite_declaration,
                extracted.sulfite_declaration,
                required="sulfite_declaration" in required,
            )
        )

    if beverage_class == BeverageClass.WINE and field_sources:
        _apply_wine_brand_label_rule(verdicts, field_sources)

    # The model's "illegible" list is a weak signal — it also lists fields
    # that simply aren't on the label. So it never raises a flag on its own;
    # it only tells the agent that a field already reported missing might be
    # printed but unreadable, which changes what they should look for.
    by_name = {v.field_name: v for v in verdicts}
    for illegible in extracted.illegible_fields:
        verdict = by_name.get(_VERDICT_FIELD_NAMES.get(illegible, illegible))
        if verdict is not None and verdict.status == MISSING and verdict.extracted_value is None:
            verdict.detail = f"{verdict.detail} {_POSSIBLY_UNREADABLE}" if verdict.detail else _POSSIBLY_UNREADABLE

    for disclosure in extracted.other_disclosures:
        detail = "Commodity-specific disclosure noticed on the label; not covered by an automated rule — human review."
        verdicts.append(Verdict("other_disclosure", None, disclosure, "presence", FLAGGED, detail))

    return verdicts
