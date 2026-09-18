"""Ground-truth label content: what is actually printed on a generated label
image. This is deliberately a separate model from `app.schemas.ExtractedLabelFields`
even though the fields line up 1:1 — this one describes what to render, the
other describes what a VLM extracted. `generate_fixtures.py` treats a
`LabelContent` as a perfect, ground-truth "extraction" to compute the expected
verdict for a case, then renders the same content into an image for the real
model to actually read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)

TITLE_CASE_WARNING = GOOD_WARNING.replace("GOVERNMENT WARNING", "Government Warning")


@dataclass
class LabelContent:
    """Everything printed on a label, split across a front and back image the
    way a real bottle label is. `beverage_class` and `imported` aren't
    printed text — they're carried along so a case can build a matching
    `ApplicationIn` without repeating them everywhere."""

    beverage_class: str
    imported: bool
    brand_name: str
    class_type: str
    name_address: str
    net_contents: str
    fanciful_name: str | None = None
    abv_percent: float | None = None
    country_of_origin: str | None = None
    appellation: str | None = None
    sulfite_declaration: str | None = None
    government_warning_text: str | None = GOOD_WARNING
    other_disclosures: list[str] = field(default_factory=list)


# Six base templates spanning all three beverage classes, domestic + imported,
# and (for malt beverage) the ABV-optional case. Each is a complete, mutually
# consistent label — cases below clone one of these and deliberately diverge
# the *declared* application fields from it, or apply a distortion to the
# *rendered image*, never both to the underlying content at once.
TEMPLATES: dict[str, LabelContent] = {
    "bourbon_domestic": LabelContent(
        beverage_class="distilled_spirits",
        imported=False,
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        name_address="Old Tom Distillery, Louisville, KY",
        net_contents="750 mL",
        abv_percent=45.0,
    ),
    "vodka_imported": LabelContent(
        beverage_class="distilled_spirits",
        imported=True,
        brand_name="NORTHWIND VODKA",
        class_type="Vodka",
        name_address="Northwind Distillers, Imported by Harbor Spirits, New York, NY",
        net_contents="1 L",
        abv_percent=40.0,
        country_of_origin="Product of Sweden",
    ),
    "cabernet_domestic": LabelContent(
        beverage_class="wine",
        imported=False,
        brand_name="STONE'S THROW",
        fanciful_name="Reserve Selection",
        class_type="Cabernet Sauvignon",
        name_address="Stone's Throw Vineyards, Napa, CA",
        net_contents="750 mL",
        abv_percent=13.5,
        appellation="Napa Valley",
        sulfite_declaration="Contains Sulfites",
    ),
    "chianti_imported": LabelContent(
        beverage_class="wine",
        imported=True,
        brand_name="CASA FIORENTINA",
        class_type="Chianti Classico",
        name_address="Casa Fiorentina, Imported by Old World Wine Co., Chicago, IL",
        net_contents="750 mL",
        abv_percent=13.0,
        country_of_origin="Product of Italy",
        appellation="Chianti Classico DOCG",
        sulfite_declaration="Contains Sulfites",
    ),
    "ipa_domestic_no_abv": LabelContent(
        beverage_class="malt_beverage",
        imported=False,
        brand_name="TRAILHEAD BREWING CO.",
        fanciful_name="Wandering Pines IPA",
        class_type="India Pale Ale",
        name_address="Trailhead Brewing Co., Bend, OR",
        net_contents="355 mL",
        abv_percent=None,
    ),
    "lager_domestic_with_abv": LabelContent(
        beverage_class="malt_beverage",
        imported=False,
        brand_name="CLEARWATER BREWING",
        class_type="American Lager",
        name_address="Clearwater Brewing Company, Duluth, MN",
        net_contents="355 mL",
        abv_percent=5.0,
    ),
}
