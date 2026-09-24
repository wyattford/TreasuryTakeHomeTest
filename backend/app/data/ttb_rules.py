"""TTB label requirement data, drawn from published TTB guidance (27 CFR
Parts 4, 5, 7, and 16 — see ttb.gov/regulated-commodities/labeling).

This module is the single source of truth for the regulatory facts the
matching engine relies on: the exact Government Warning text, the ABV
tolerance, the per-class standard container sizes, and which fields have
placement rules. Keeping these as plain data
(not scattered through the matching logic) makes them easy to audit against
the regulation and easy to unit test in isolation.
"""

from __future__ import annotations

from enum import StrEnum


class BeverageClass(StrEnum):
    DISTILLED_SPIRITS = "distilled_spirits"
    WINE = "wine"
    MALT_BEVERAGE = "malt_beverage"


# 27 CFR Part 16 / Alcoholic Beverage Labeling Act of 1988. Required verbatim,
# with "GOVERNMENT WARNING" in capital letters and bold type; the rest of the
# statement must not be bold. See TTB "Health Warning Statement" guidance.
GOVERNMENT_WARNING_TEXT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

# 27 CFR 5.65 — labeled ABV may differ from actual ABV by up to this many
# percentage points before it's a compliance issue.
ABV_TOLERANCE_PERCENTAGE_POINTS = 0.3

# 27 CFR 5.203(a) — authorized standard-of-fill container sizes for distilled
# spirits, in milliliters. A net-contents value that isn't one of these is a
# compliance flag independent of whether it matches the application.
DISTILLED_SPIRITS_FILL_SIZES_ML: frozenset[float] = frozenset(
    {
        3750,
        3000,
        2000,
        1800,
        1750,
        1500,
        1000,
        945,
        900,
        750,
        720,
        710,
        700,
        570,
        500,
        475,
        375,
        355,
        350,
        331,
        250,
        200,
        187,
        100,
        50,
    }
)

# 27 CFR 4.72(a) — authorized standard-of-fill container sizes for wine, in
# milliliters. 4.72(b) additionally allows any container of 4 liters or more
# filled in even liters (4 L, 5 L, 6 L, ...) — see is_standard_fill().
WINE_FILL_SIZES_ML: frozenset[float] = frozenset(
    {
        3000,
        2250,
        1800,
        1500,
        1000,
        750,
        720,
        700,
        620,
        600,
        568,
        550,
        500,
        473,
        375,
        360,
        355,
        330,
        300,
        250,
        200,
        187,
        180,
        100,
        50,
    }
)
WINE_LARGE_CONTAINER_MIN_ML = 4000

# Labels often state net contents in US units that don't convert to a whole
# number of milliliters (12 FL OZ = 354.88 mL, 25.4 FL OZ = 751.2 mL), so
# container-size comparisons allow this much slack instead of demanding exact
# equality.
NET_CONTENTS_TOLERANCE_ML = 2.0

# Proof is defined as twice the alcohol content by volume. Labels round both
# figures, so allow a little slack before calling them inconsistent.
PROOF_TOLERANCE = 0.5

# 27 CFR 4.32(a) — on wine, these must appear on the brand (front) label; the
# rest of the mandatory information may appear on any label on the container.
WINE_BRAND_LABEL_FIELDS: tuple[str, ...] = ("brand_name", "class_type")


def standard_fill_sizes_for(beverage_class: BeverageClass) -> frozenset[float] | None:
    """Authorized container sizes for a class, or None if the class has no
    federal standard of fill (malt beverages don't)."""

    return {
        BeverageClass.DISTILLED_SPIRITS: DISTILLED_SPIRITS_FILL_SIZES_ML,
        BeverageClass.WINE: WINE_FILL_SIZES_ML,
    }.get(beverage_class)


def is_standard_fill(beverage_class: BeverageClass, ml: float) -> bool:
    sizes = standard_fill_sizes_for(beverage_class)
    if sizes is None:
        return True
    if any(abs(ml - size) <= NET_CONTENTS_TOLERANCE_ML for size in sizes):
        return True
    if beverage_class == BeverageClass.WINE and ml >= WINE_LARGE_CONTAINER_MIN_ML:
        return abs(ml / 1000 - round(ml / 1000)) * 1000 <= NET_CONTENTS_TOLERANCE_ML
    return False


# Fields required on every label, regardless of beverage class.
COMMON_REQUIRED_FIELDS: tuple[str, ...] = (
    "brand_name",
    "class_type",
    "name_address",
    "net_contents",
    "government_warning",
)

# Fields required in addition to COMMON_REQUIRED_FIELDS, per beverage class.
# abv is required for spirits and wine, but only "mandatory or optional"
# (state-dependent) for malt beverages federally — modeled as not
# unconditionally required here, so we don't flag a false negative on beer
# labels that omit it.
CLASS_SPECIFIC_REQUIRED_FIELDS: dict[BeverageClass, tuple[str, ...]] = {
    BeverageClass.DISTILLED_SPIRITS: ("abv",),
    BeverageClass.WINE: ("abv", "sulfite_declaration"),
    BeverageClass.MALT_BEVERAGE: (),
}

# country_of_origin is required only for imports, independent of class.
IMPORT_ONLY_FIELDS: tuple[str, ...] = ("country_of_origin",)


def required_fields_for(beverage_class: BeverageClass, imported: bool) -> set[str]:
    fields = set(COMMON_REQUIRED_FIELDS) | set(CLASS_SPECIFIC_REQUIRED_FIELDS[beverage_class])
    if imported:
        fields |= set(IMPORT_ONLY_FIELDS)
    return fields
