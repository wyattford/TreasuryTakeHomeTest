from app.matching.engine import FLAGGED, MATCH, MISMATCH, MISSING, compare
from app.schemas import ApplicationIn, ExtractedLabelFields

GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


def _application(**overrides) -> ApplicationIn:
    defaults = {
        "beverage_class": "distilled_spirits",
        "imported": False,
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv": 45.0,
        "net_contents": "750 mL",
        "name_address": "Old Tom Distillery, Louisville, KY",
    }
    defaults.update(overrides)
    return ApplicationIn(**defaults)


def _extracted(**overrides) -> ExtractedLabelFields:
    defaults = {
        "brand_name": "OLD TOM DISTILLERY",
        "class_type": "Kentucky Straight Bourbon Whiskey",
        "abv_percent": 45.0,
        "net_contents": "750 mL",
        "name_address": "Old Tom Distillery, Louisville, KY",
        "government_warning_text": GOOD_WARNING,
    }
    defaults.update(overrides)
    return ExtractedLabelFields(**defaults)


def _verdict(verdicts, field_name):
    return next(v for v in verdicts if v.field_name == field_name)


def test_exact_match_label_passes_every_field():
    verdicts = compare(_application(), _extracted())
    assert all(v.status == MATCH for v in verdicts)


def test_brand_name_case_and_punctuation_differences_still_match():
    # Dave's example from the stakeholder interview: "STONE'S THROW" on the
    # label vs "Stone's Throw" on the application should not be a mismatch.
    verdicts = compare(
        _application(brand_name="Stone's Throw"),
        _extracted(brand_name="STONE'S THROW"),
    )
    assert _verdict(verdicts, "brand_name").status == MATCH


def test_abv_within_tolerance_matches():
    verdicts = compare(_application(abv=45.0), _extracted(abv_percent=45.2))
    assert _verdict(verdicts, "abv").status == MATCH


def test_abv_outside_tolerance_mismatches():
    verdicts = compare(_application(abv=45.0), _extracted(abv_percent=46.0))
    assert _verdict(verdicts, "abv").status == MISMATCH


def test_net_contents_off_standard_fill_is_flagged():
    verdicts = compare(_application(net_contents="600 mL"), _extracted(net_contents="600 mL"))
    assert _verdict(verdicts, "net_contents").status == FLAGGED


def test_warning_statement_title_case_is_a_mismatch():
    # Jenny's example: "Government Warning" in title case instead of all caps
    # is a real compliance failure, not a stylistic difference.
    bad_warning = GOOD_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
    verdicts = compare(_application(), _extracted(government_warning_text=bad_warning))
    assert _verdict(verdicts, "government_warning").status == MISMATCH


def test_missing_warning_statement_is_missing_not_mismatch():
    verdicts = compare(_application(), _extracted(government_warning_text=None))
    assert _verdict(verdicts, "government_warning").status == MISSING


def test_illegible_fields_are_flagged_for_human_review():
    verdicts = compare(_application(), _extracted(illegible_fields=["net_contents"]))
    illegible = [v for v in verdicts if v.field_name == "illegible:net_contents"]
    assert len(illegible) == 1
    assert illegible[0].status == FLAGGED
