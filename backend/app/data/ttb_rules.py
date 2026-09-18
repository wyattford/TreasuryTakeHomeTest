"""TTB label requirement data, drawn from published TTB guidance (27 CFR
Parts 4, 5, 7, and 16 — see ttb.gov/regulated-commodities/labeling).

This module is the single source of truth for the regulatory facts the
matching engine relies on: the exact Government Warning text, the ABV
tolerance, and the standard container sizes. Keeping these as plain data
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
STANDARD_FILL_SIZES_ML: set[float] = {
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
