"""The test matrix: ~40 cases, each a (label template, deliberate declared-data
deviation, image distortion) triple.

Every case clones a base `LabelContent` template (the ground truth of what's
printed on the label) and optionally:
  - `label_overrides`: changes what's actually printed (e.g. remove the
    Government Warning, use a non-standard fill size, title-case the warning).
  - `declared_overrides`: changes what the *applicant declares*, independent
    of the label, to deliberately create a match/mismatch/flag against the
    (possibly-overridden) label content.
  - `distortion`: how the rendered image is degraded before it's shown to the
    model (see distortions.py).

`generate_fixtures.py` computes each case's expected verdicts by running the
real matching engine (`app.matching.engine.compare`) against the label content
treated as a perfect extraction — so "expected" is never hand-typed, it's
whatever the production rules actually say should happen. That also means a
case's tag (e.g. `expect_flagged`) is documentation of *intent*, not what
drives the pass/fail check — a case can be tagged `known_limitation` if its
computed expectation reveals a real quirk in the matching engine itself
rather than an OCR failure (none currently are; two were until the ABV and
net-contents bugs they exposed got fixed — see README.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from label_content import TITLE_CASE_WARNING

REWORDED_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy. (2) Consumption of "
    "alcoholic beverages impairs your ability to drive a car or operate "
    "machinery, and may cause health problems."
)


@dataclass
class CaseSpec:
    id: str
    description: str
    template: str
    label_overrides: dict = field(default_factory=dict)
    declared_overrides: dict = field(default_factory=dict)
    distortion: str = "clean"
    tags: list[str] = field(default_factory=list)


CASES: list[CaseSpec] = [
    # --- Baselines: one clean, fully-matching case per template. -----------
    CaseSpec(
        "bourbon_clean_correct",
        "Bourbon, clean image, declared data matches label exactly.",
        "bourbon_domestic",
        tags=["baseline"],
    ),
    CaseSpec(
        "vodka_clean_correct",
        "Imported vodka, clean image, matches exactly.",
        "vodka_imported",
        tags=["baseline", "import"],
    ),
    CaseSpec(
        "cabernet_clean_correct",
        "Domestic wine, clean image, matches exactly.",
        "cabernet_domestic",
        tags=["baseline", "wine"],
    ),
    CaseSpec(
        "chianti_clean_correct",
        "Imported wine, clean image, matches exactly.",
        "chianti_imported",
        tags=["baseline", "wine", "import"],
    ),
    CaseSpec(
        "ipa_clean_correct",
        "Malt beverage with no ABV declared (federally optional) and none printed on the label, clean image.",
        "ipa_domestic_no_abv",
        tags=["baseline", "malt"],
    ),
    CaseSpec(
        "lager_clean_correct",
        "Malt beverage with ABV declared, clean image.",
        "lager_domestic_with_abv",
        tags=["baseline", "malt"],
    ),
    # --- Fuzzy match: brand_name / class_type / name_address. --------------
    CaseSpec(
        "brand_name_case_punct_tolerant",
        "Brand name differs only in case/punctuation from the label — must still MATCH.",
        "bourbon_domestic",
        declared_overrides={"brand_name": "Old Tom Distillery"},
        tags=["fuzzy", "expect_match"],
    ),
    CaseSpec(
        "brand_name_close_flagged",
        "Brand name is close but not identical to the label — should be FLAGGED, not hard-failed.",
        "bourbon_domestic",
        declared_overrides={"brand_name": "Old Tom Distillery Co"},
        tags=["fuzzy", "expect_flagged"],
    ),
    CaseSpec(
        "brand_name_hard_mismatch",
        "Declared brand name is a different name entirely — should MISMATCH.",
        "bourbon_domestic",
        declared_overrides={"brand_name": "Silver Fox Distillery"},
        tags=["fuzzy", "expect_mismatch"],
    ),
    CaseSpec(
        "class_type_close_flagged",
        "Class/type has a minor typo relative to the label — should be FLAGGED.",
        "cabernet_domestic",
        declared_overrides={"class_type": "Cabernet Savignon"},
        tags=["fuzzy", "expect_flagged", "wine"],
    ),
    CaseSpec(
        "class_type_hard_mismatch",
        "Declared class/type is a different varietal than the label — should MISMATCH.",
        "cabernet_domestic",
        declared_overrides={"class_type": "Merlot"},
        tags=["fuzzy", "expect_mismatch", "wine"],
    ),
    CaseSpec(
        "name_address_close_flagged",
        "Declared name/address has a minor difference from the label — should be FLAGGED.",
        "vodka_imported",
        declared_overrides={"name_address": "Northwind Distillers, Imported by Harbor Spirits Inc., New York, NY"},
        tags=["fuzzy", "expect_flagged", "import"],
    ),
    CaseSpec(
        "name_address_hard_mismatch",
        "Declared name/address is a substantially different statement — should MISMATCH.",
        "vodka_imported",
        declared_overrides={"name_address": "Fjordlight Spirits, Imported by Continental Beverage, Miami, FL"},
        tags=["fuzzy", "expect_mismatch", "import"],
    ),
    # --- ABV tolerance. ------------------------------------------------------
    CaseSpec(
        "abv_within_tolerance",
        "Declared ABV is within the +/-0.3 point tolerance of the label — should MATCH.",
        "bourbon_domestic",
        declared_overrides={"abv": 45.2},
        tags=["tolerance", "expect_match"],
    ),
    CaseSpec(
        "abv_outside_tolerance",
        "Declared ABV is well outside tolerance — should MISMATCH.",
        "bourbon_domestic",
        declared_overrides={"abv": 43.0},
        tags=["tolerance", "expect_mismatch"],
    ),
    CaseSpec(
        "abv_declared_but_not_on_label",
        "Applicant declares an ABV for a malt beverage that the label doesn't print at all — should be MISSING.",
        "ipa_domestic_no_abv",
        declared_overrides={"abv": 6.0},
        tags=["tolerance", "expect_missing", "malt"],
    ),
    CaseSpec(
        "abv_not_declared_but_on_label",
        "Label prints an ABV but the application never declared one — should be MISSING.",
        "lager_domestic_with_abv",
        declared_overrides={"abv": None},
        tags=["tolerance", "expect_missing", "malt"],
    ),
    # --- Net contents (enum). -------------------------------------------------
    CaseSpec(
        "net_contents_nonstandard_fill",
        "Both label and declared value agree on a non-standard fill size — should be FLAGGED.",
        "bourbon_domestic",
        label_overrides={"net_contents": "600 mL"},
        declared_overrides={"net_contents": "600 mL"},
        tags=["enum", "expect_flagged"],
    ),
    CaseSpec(
        "net_contents_declared_mismatch",
        "Label shows one standard size, application declares a different standard size — should MISMATCH.",
        "bourbon_domestic",
        declared_overrides={"net_contents": "1 L"},
        tags=["enum", "expect_mismatch"],
    ),
    CaseSpec(
        "net_contents_unparseable_declared_unit",
        (
            "Application declares net contents in a unit the parser doesn't recognize (fluid ounces) while the "
            "label actually shows a different, standard mL size — since it can't be verified either way, should "
            "be FLAGGED rather than silently passed as a match."
        ),
        "bourbon_domestic",
        declared_overrides={"net_contents": "12 FL OZ"},
        tags=["enum", "expect_flagged"],
    ),
    # --- Government Warning (exact). ------------------------------------------
    CaseSpec(
        "warning_missing",
        "Label has no Government Warning statement at all — should be MISSING.",
        "bourbon_domestic",
        label_overrides={"government_warning_text": None},
        tags=["exact", "expect_missing"],
    ),
    CaseSpec(
        "warning_title_case",
        "Government Warning is present but 'Government Warning' is title-cased, not all-caps — should MISMATCH.",
        "bourbon_domestic",
        label_overrides={"government_warning_text": TITLE_CASE_WARNING},
        tags=["exact", "expect_mismatch"],
    ),
    CaseSpec(
        "warning_reworded",
        "Government Warning is present and all-caps but the wording has been altered — should MISMATCH.",
        "bourbon_domestic",
        label_overrides={"government_warning_text": REWORDED_WARNING},
        tags=["exact", "expect_mismatch"],
    ),
    # --- Country of origin (presence, imports only). --------------------------
    CaseSpec(
        "country_of_origin_missing_on_import",
        "Imported product with no country-of-origin statement on the label — should be MISSING.",
        "vodka_imported",
        label_overrides={"country_of_origin": None},
        tags=["presence", "expect_missing", "import"],
    ),
    CaseSpec(
        "country_of_origin_mismatch",
        "Label states one country of origin, application declares a different one — should be FLAGGED.",
        "vodka_imported",
        declared_overrides={"country_of_origin": "Product of Norway"},
        tags=["presence", "expect_flagged", "import"],
    ),
    # --- Wine-specific presence fields. ---------------------------------------
    CaseSpec(
        "sulfite_declaration_missing",
        "Wine label omits the sulfite declaration, which is required for wine — should be MISSING.",
        "cabernet_domestic",
        label_overrides={"sulfite_declaration": None},
        tags=["presence", "expect_missing", "wine"],
    ),
    CaseSpec(
        "appellation_absent_optional",
        "Wine label has no appellation statement, which is optional — should still MATCH.",
        "cabernet_domestic",
        label_overrides={"appellation": None},
        tags=["presence", "expect_match", "wine"],
    ),
    # --- Multi-field combinations. ---------------------------------------------
    CaseSpec(
        "combo_brand_and_abv_wrong",
        "Both brand name and ABV are wrong on the same application — both should be flagged independently.",
        "bourbon_domestic",
        declared_overrides={"brand_name": "Silver Fox Distillery", "abv": 43.0},
        tags=["combo", "expect_mismatch"],
    ),
    CaseSpec(
        "combo_wine_multiple_wrong",
        "Brand name, class/type, and country of origin are all wrong on an imported wine.",
        "chianti_imported",
        declared_overrides={
            "brand_name": "Villa Rosati",
            "class_type": "Sangiovese",
            "country_of_origin": "Product of Spain",
        },
        tags=["combo", "expect_mismatch", "wine", "import"],
    ),
    # --- Distortions: does the model still read the label correctly? ---------
    # Each distortion is applied once to an otherwise-correct case (checking
    # for false mismatches caused by misreads) and once to a case with a real,
    # deliberate mismatch baked in (checking the real discrepancy still gets
    # caught despite the noisy image).
    CaseSpec(
        "blur_correct",
        "Clean data, moderately blurred image.",
        "bourbon_domestic",
        distortion="blur",
        tags=["distortion", "expect_match"],
    ),
    CaseSpec(
        "blur_incorrect",
        "Out-of-tolerance ABV, moderately blurred image.",
        "bourbon_domestic",
        declared_overrides={"abv": 43.0},
        distortion="blur",
        tags=["distortion", "expect_mismatch"],
    ),
    CaseSpec(
        "rotate_correct",
        "Clean data, skewed/rotated image (photographed at an angle).",
        "cabernet_domestic",
        distortion="rotate",
        tags=["distortion", "expect_match", "wine"],
    ),
    CaseSpec(
        "rotate_incorrect",
        "Wrong brand name, skewed/rotated image.",
        "cabernet_domestic",
        declared_overrides={"brand_name": "Rolling Hills Cellars"},
        distortion="rotate",
        tags=["distortion", "expect_mismatch", "wine"],
    ),
    CaseSpec(
        "low_contrast_correct",
        "Clean data, washed-out low-contrast image.",
        "vodka_imported",
        distortion="low_contrast",
        tags=["distortion", "expect_match", "import"],
    ),
    CaseSpec(
        "low_contrast_incorrect",
        "Wrong declared country of origin, washed-out low-contrast image.",
        "vodka_imported",
        declared_overrides={"country_of_origin": "Product of Norway"},
        distortion="low_contrast",
        tags=["distortion", "expect_flagged", "import"],
    ),
    CaseSpec(
        "noise_correct",
        "Clean data, grainy/noisy image.",
        "chianti_imported",
        distortion="noise",
        tags=["distortion", "expect_match", "wine", "import"],
    ),
    CaseSpec(
        "noise_incorrect",
        "Wrong class/type, grainy/noisy image.",
        "chianti_imported",
        declared_overrides={"class_type": "Pinot Noir"},
        distortion="noise",
        tags=["distortion", "expect_mismatch", "wine", "import"],
    ),
    CaseSpec(
        "jpeg_correct",
        "Clean data, heavily JPEG-compressed image.",
        "ipa_domestic_no_abv",
        distortion="jpeg",
        tags=["distortion", "expect_match", "malt"],
    ),
    CaseSpec(
        "jpeg_incorrect",
        "Mismatched net contents, heavily JPEG-compressed image.",
        "lager_domestic_with_abv",
        declared_overrides={"net_contents": "750 mL"},
        distortion="jpeg",
        tags=["distortion", "expect_mismatch", "malt"],
    ),
    CaseSpec(
        "glare_correct",
        "Clean data, simulated glare/reflection over part of the label.",
        "lager_domestic_with_abv",
        distortion="glare",
        tags=["distortion", "expect_match", "malt"],
    ),
    CaseSpec(
        "glare_incorrect",
        "Wrong brand name, simulated glare/reflection over part of the label.",
        "lager_domestic_with_abv",
        declared_overrides={"brand_name": "Riverbend Brewing"},
        distortion="glare",
        tags=["distortion", "expect_mismatch", "malt"],
    ),
    CaseSpec(
        "combo_blur_rotate_correct",
        "Clean data, blurred AND rotated image.",
        "bourbon_domestic",
        distortion="blur_rotate",
        tags=["distortion", "expect_match"],
    ),
    CaseSpec(
        "combo_blur_rotate_incorrect",
        "Missing Government Warning, blurred AND rotated image.",
        "bourbon_domestic",
        label_overrides={"government_warning_text": None},
        distortion="blur_rotate",
        tags=["distortion", "expect_missing"],
    ),
]
