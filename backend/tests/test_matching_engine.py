import pytest

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


@pytest.mark.parametrize(
    "altered",
    [
        GOOD_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENT WARNING"),  # colon dropped
        GOOD_WARNING.replace("(1)", "1").replace("(2)", "2"),  # numbering parentheses dropped
    ],
)
def test_warning_statement_punctuation_counts(altered):
    verdicts = compare(_application(), _extracted(government_warning_text=altered))
    assert _verdict(verdicts, "government_warning").status == MISMATCH


def test_warning_statement_ignores_line_breaks_and_extra_spaces():
    reflowed = GOOD_WARNING.replace(" (2) ", "\n(2) ").replace("women", " women ")
    verdicts = compare(_application(), _extracted(government_warning_text=reflowed))
    assert _verdict(verdicts, "government_warning").status == MATCH


def test_missing_warning_statement_is_missing_not_mismatch():
    verdicts = compare(_application(), _extracted(government_warning_text=None))
    assert _verdict(verdicts, "government_warning").status == MISSING


def test_illegible_missing_field_gets_check_by_eye_note():
    verdicts = compare(_application(), _extracted(net_contents=None, illegible_fields=["net_contents"]))
    verdict = _verdict(verdicts, "net_contents")
    assert verdict.status == MISSING
    assert "check the label by eye" in verdict.detail


def test_illegible_never_adds_flags_of_its_own():
    # The model also lists fields it read fine, or that simply aren't on the
    # label, as "illegible" — that alone must not route a label to review.
    verdicts = compare(_application(), _extracted(illegible_fields=["net_contents", "proof", "appellation"]))
    assert all(v.status == MATCH for v in verdicts), [(v.field_name, v.status) for v in verdicts]


def test_abv_not_declared_and_not_on_label_matches_when_not_required():
    # Malt beverages don't unconditionally require ABV federally — a beer
    # label that omits it, matching an application that also omits it, is
    # consistent and should not be flagged.
    verdicts = compare(
        _application(beverage_class="malt_beverage", abv=None),
        _extracted(abv_percent=None),
    )
    assert _verdict(verdicts, "abv").status == MATCH


def test_abv_not_declared_and_not_on_label_is_missing_when_required():
    # Distilled spirits do require ABV — both sides omitting it is a real
    # compliance gap, not a consistent absence.
    verdicts = compare(
        _application(beverage_class="distilled_spirits", abv=None),
        _extracted(abv_percent=None),
    )
    assert _verdict(verdicts, "abv").status == MISSING


def test_net_contents_declared_in_unparseable_unit_is_flagged_not_matched():
    # A declared value the parser can't understand must not silently pass
    # just because it can't be compared — it's flagged as unverifiable.
    verdicts = compare(
        _application(net_contents="one bottle"),
        _extracted(net_contents="750 mL"),
    )
    assert _verdict(verdicts, "net_contents").status == FLAGGED


def test_net_contents_declared_in_fluid_ounces_matches_metric_label():
    verdicts = compare(
        _application(beverage_class="malt_beverage", net_contents="12 FL OZ"),
        _extracted(net_contents="355 mL"),
    )
    assert _verdict(verdicts, "net_contents").status == MATCH


def test_net_contents_declared_in_fluid_ounces_mismatches_different_size():
    verdicts = compare(
        _application(beverage_class="malt_beverage", net_contents="12 FL OZ"),
        _extracted(net_contents="16 FL OZ"),
    )
    assert _verdict(verdicts, "net_contents").status == MISMATCH


def test_malt_beverage_has_no_standard_of_fill():
    # Beer comes in 12, 16, 19.2, 22 oz... — none of it is a spirits standard
    # of fill, and none of it should be flagged for that.
    verdicts = compare(
        _application(beverage_class="malt_beverage", net_contents="19.2 FL OZ"),
        _extracted(net_contents="19.2 FL OZ"),
    )
    assert _verdict(verdicts, "net_contents").status == MATCH


def test_wine_uses_wine_standards_of_fill():
    # 620 mL is a wine standard of fill (27 CFR 4.72) but not a spirits one.
    wine = compare(_application(beverage_class="wine", net_contents="620 mL"), _extracted(net_contents="620 mL"))
    spirits = compare(_application(net_contents="620 mL"), _extracted(net_contents="620 mL"))
    assert _verdict(wine, "net_contents").status == MATCH
    assert _verdict(spirits, "net_contents").status == FLAGGED


def test_wine_allows_even_liter_containers_of_4_liters_or_more():
    ok = compare(_application(beverage_class="wine", net_contents="5 L"), _extracted(net_contents="5 L"))
    odd = compare(_application(beverage_class="wine", net_contents="4.5 L"), _extracted(net_contents="4.5 L"))
    assert _verdict(ok, "net_contents").status == MATCH
    assert _verdict(odd, "net_contents").status == FLAGGED


def test_nothing_declared_checks_label_on_its_own():
    verdicts = compare(ApplicationIn(beverage_class="distilled_spirits"), _extracted())
    assert all(v.status == MATCH for v in verdicts), [(v.field_name, v.status) for v in verdicts]


def test_nothing_declared_still_catches_missing_required_fields():
    verdicts = compare(ApplicationIn(beverage_class="distilled_spirits"), _extracted(brand_name=None, abv_percent=None))
    assert _verdict(verdicts, "brand_name").status == MISSING
    assert _verdict(verdicts, "abv").status == MISSING


def test_nothing_declared_still_flags_nonstandard_container():
    verdicts = compare(ApplicationIn(beverage_class="distilled_spirits"), _extracted(net_contents="600 mL"))
    assert _verdict(verdicts, "net_contents").status == FLAGGED


def test_proof_consistent_with_abv_matches():
    verdicts = compare(_application(), _extracted(abv_percent=45.0, proof=90))
    assert _verdict(verdicts, "proof").status == MATCH


def test_proof_inconsistent_with_abv_mismatches():
    verdicts = compare(_application(), _extracted(abv_percent=45.0, proof=80))
    assert _verdict(verdicts, "proof").status == MISMATCH


def test_no_proof_statement_means_no_proof_verdict():
    verdicts = compare(_application(), _extracted())
    assert not [v for v in verdicts if v.field_name == "proof"]


def test_wine_brand_name_only_on_back_label_is_flagged():
    application = _application(beverage_class="wine", abv=13.5, net_contents="750 mL")
    extracted = _extracted(abv_percent=13.5, sulfite_declaration="Contains Sulfites")
    verdicts = compare(application, extracted, {"brand_name": "back", "class_type": "front"})
    assert _verdict(verdicts, "brand_name").status == FLAGGED
    assert _verdict(verdicts, "class_type").status == MATCH


def test_front_label_placement_rule_is_wine_only():
    verdicts = compare(_application(), _extracted(), {"brand_name": "back"})
    assert _verdict(verdicts, "brand_name").status == MATCH


def test_illegible_extraction_field_maps_to_result_field_name():
    verdicts = compare(_application(), _extracted(abv_percent=None, illegible_fields=["abv_percent"]))
    assert "check the label by eye" in _verdict(verdicts, "abv").detail


def test_illegible_optional_field_is_not_flagged():
    # The model marks optional fields it didn't find (proof on most whiskey
    # labels, appellation on non-wine) as illegible; that's noise.
    verdicts = compare(_application(), _extracted(illegible_fields=["proof", "appellation"]))
    assert not [v for v in verdicts if v.field_name.startswith("illegible:")]
