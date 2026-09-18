"""Compares an application's declared fields against a label's extracted
fields and produces one verdict per field.

Philosophy: legally-exact rules are decided deterministically in code, never
left to the vision model's own judgment. The model's job is extraction; this
module's job is the compliance decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.ttb_rules import (
    ABV_TOLERANCE_PERCENTAGE_POINTS,
    GOVERNMENT_WARNING_TEXT,
    STANDARD_FILL_SIZES_ML,
    BeverageClass,
    required_fields_for,
)
from app.matching.text_utils import FUZZY_MATCH_THRESHOLD, normalize, parse_net_contents_ml, similarity
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


def _fuzzy_verdict(field_name: str, declared: str | None, extracted: str | None) -> Verdict:
    if not declared:
        return Verdict(field_name, declared, extracted, "fuzzy", MISSING, "Not declared on the application.")
    if not extracted:
        return Verdict(field_name, declared, extracted, "fuzzy", MISSING, "Not found on the label.")
    ratio = similarity(declared, extracted)
    if normalize(declared) == normalize(extracted):
        return Verdict(field_name, declared, extracted, "fuzzy", MATCH)
    if ratio >= FUZZY_MATCH_THRESHOLD:
        detail = f"Close but not identical ({ratio:.0%} similar) — worth a human glance."
        return Verdict(field_name, declared, extracted, "fuzzy", FLAGGED, detail)
    return Verdict(field_name, declared, extracted, "fuzzy", MISMATCH, f"Only {ratio:.0%} similar.")


def _abv_verdict(declared: float | None, extracted: float | None) -> Verdict:
    field_name = "abv"
    if declared is None:
        return Verdict(field_name, None, _fmt(extracted), "tolerance", MISSING, "Not declared on the application.")
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


def _net_contents_verdict(declared: str, extracted: str | None) -> Verdict:
    field_name = "net_contents"
    if not extracted:
        return Verdict(field_name, declared, None, "enum", MISSING, "Not found on the label.")
    extracted_ml = parse_net_contents_ml(extracted)
    if extracted_ml is None:
        detail = "Couldn't parse a container size from the label text."
        return Verdict(field_name, declared, extracted, "enum", FLAGGED, detail)
    if extracted_ml not in STANDARD_FILL_SIZES_ML:
        detail = f"{extracted_ml:g} mL is not one of the standard authorized container sizes (27 CFR 5.203(a))."
        return Verdict(field_name, declared, extracted, "enum", FLAGGED, detail)
    declared_ml = parse_net_contents_ml(declared)
    if declared_ml is not None and declared_ml != extracted_ml:
        return Verdict(field_name, declared, extracted, "enum", MISMATCH, "Label's net contents don't match what was declared.")
    return Verdict(field_name, declared, extracted, "enum", MATCH)


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
    if normalize(extracted_text) == normalize(GOVERNMENT_WARNING_TEXT):
        return Verdict(field_name, GOVERNMENT_WARNING_TEXT, extracted_text, "exact", MATCH)
    return Verdict(
        field_name,
        GOVERNMENT_WARNING_TEXT,
        extracted_text,
        "exact",
        MISMATCH,
        "Wording does not match the statement prescribed verbatim by 27 CFR 16.21.",
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


def compare(application: ApplicationIn, extracted: ExtractedLabelFields) -> list[Verdict]:
    verdicts: list[Verdict] = [
        _fuzzy_verdict("brand_name", application.brand_name, extracted.brand_name),
        _fuzzy_verdict("class_type", application.class_type, extracted.class_type),
        _abv_verdict(application.abv, extracted.abv_percent),
        _net_contents_verdict(application.net_contents, extracted.net_contents),
        _fuzzy_verdict("name_address", application.name_address, extracted.name_address),
        _warning_verdict(extracted.government_warning_text),
    ]

    required = required_fields_for(BeverageClass(application.beverage_class), application.imported)

    if application.imported or "country_of_origin" in required or application.country_of_origin:
        verdicts.append(
            _presence_verdict(
                "country_of_origin",
                application.country_of_origin,
                extracted.country_of_origin,
                required="country_of_origin" in required,
            )
        )

    if application.beverage_class == BeverageClass.WINE:
        verdicts.append(_presence_verdict("appellation", application.appellation, extracted.appellation, required=False))
        verdicts.append(
            _presence_verdict(
                "sulfite_declaration",
                application.sulfite_declaration,
                extracted.sulfite_declaration,
                required="sulfite_declaration" in required,
            )
        )

    for illegible in extracted.illegible_fields:
        detail = "Model could not read this field confidently — needs a human look."
        verdicts.append(Verdict(f"illegible:{illegible}", None, None, "presence", FLAGGED, detail))

    for disclosure in extracted.other_disclosures:
        detail = "Commodity-specific disclosure noticed on the label; not covered by an automated rule — human review."
        verdicts.append(Verdict("other_disclosure", None, disclosure, "presence", FLAGGED, detail))

    return verdicts
