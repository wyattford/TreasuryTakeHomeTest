from app.matching.merge import merge_extractions
from app.schemas import ExtractedLabelFields


def test_front_values_win_and_back_fills_gaps():
    front = ExtractedLabelFields(brand_name="OLD TOM", class_type="Bourbon")
    back = ExtractedLabelFields(brand_name="Old Tom Distillery", government_warning_text="GOVERNMENT WARNING: ...")
    merged, sources = merge_extractions(front, back)
    assert merged.brand_name == "OLD TOM"
    assert merged.government_warning_text == "GOVERNMENT WARNING: ..."
    assert sources == {"brand_name": "front", "class_type": "front", "government_warning_text": "back"}


def test_back_label_name_and_address_wins():
    front = ExtractedLabelFields(brand_name="OLD TOM DISTILLERY", name_address="OLD TOM DISTILLERY")
    back = ExtractedLabelFields(name_address="Old Tom Distillery, Louisville, KY")
    merged, sources = merge_extractions(front, back)
    assert merged.name_address == "Old Tom Distillery, Louisville, KY"
    assert sources["name_address"] == "back"


def test_single_image_merges_to_itself():
    front = ExtractedLabelFields(brand_name="OLD TOM", other_disclosures=["Contains FD&C Yellow No. 5"])
    merged, sources = merge_extractions(front, None)
    assert merged == front
    assert sources == {"brand_name": "front"}


def test_field_read_on_one_side_is_not_illegible():
    front = ExtractedLabelFields(brand_name="OLD TOM", illegible_fields=["brand_name"])
    back = ExtractedLabelFields(illegible_fields=["brand_name", "net_contents"])
    merged, _ = merge_extractions(front, back)
    assert merged.illegible_fields == ["net_contents"]


def test_disclosures_are_deduplicated_across_sides():
    front = ExtractedLabelFields(other_disclosures=["Contains Sulfites"])
    back = ExtractedLabelFields(other_disclosures=["CONTAINS SULFITES", "Contains FD&C Yellow No. 5"])
    merged, _ = merge_extractions(front, back)
    assert merged.other_disclosures == ["Contains Sulfites", "Contains FD&C Yellow No. 5"]


def test_back_label_warning_wins_over_front_reading():
    # The model sometimes "reads" a warning off a front label that has none.
    front = ExtractedLabelFields(government_warning_text="GOVERNMENT WARNING: (1) According to the Surgeon General...")
    back = ExtractedLabelFields(government_warning_text="Government Warning: (1) According to the Surgeon General...")
    merged, sources = merge_extractions(front, back)
    assert merged.government_warning_text.startswith("Government Warning")
    assert sources["government_warning_text"] == "back"


def test_front_warning_used_when_back_has_none():
    front = ExtractedLabelFields(government_warning_text="GOVERNMENT WARNING: (1) ...")
    merged, sources = merge_extractions(front, ExtractedLabelFields())
    assert sources["government_warning_text"] == "front"
