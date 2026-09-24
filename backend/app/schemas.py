from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.data.ttb_rules import BeverageClass


class ApplicationIn(BaseModel):
    """What an applicant declares on TTB F 5100.31 — submitted alongside the
    label image(s) so we have something to check the label against.

    Only the beverage class and import status are required, since they decide
    which rules apply. Every declared value is optional: a field left blank is
    checked against the label's own requirements instead of against the
    application (e.g. "is a brand name printed at all?")."""

    beverage_class: BeverageClass
    imported: bool = False
    brand_name: str | None = None
    fanciful_name: str | None = None
    class_type: str | None = None
    abv: float | None = None
    net_contents: str | None = None
    name_address: str | None = None
    country_of_origin: str | None = None
    appellation: str | None = None
    sulfite_declaration: str | None = None


class ApplicationOut(ApplicationIn):
    id: str
    submitted_at: datetime

    model_config = {"from_attributes": True}


class ExtractedApplicationFields(BaseModel):
    """Partial ``ApplicationIn`` fields read from a filled-in TTB F 5100.31
    PDF's form fields. Only the subset the real form actually captures —
    class_type, abv, net_contents, country_of_origin, and
    sulfite_declaration aren't on the application itself and are never
    present here; the frontend leaves those for manual entry."""

    beverage_class: BeverageClass | None = None
    imported: bool | None = None
    brand_name: str | None = None
    fanciful_name: str | None = None
    name_address: str | None = None
    appellation: str | None = None


class ExtractedLabelFields(BaseModel):
    """The JSON shape we ask the vision model to fill in, once per label image.

    Sent to Ollama as a schema described in the prompt text (NOT via Ollama's
    `format`/grammar-constrained decoding — see the note in
    app/inference/ollama_client.py on why that mechanism was dropped after
    live testing showed it silently drops and misassigns fields with this
    model, even though it mechanically guarantees syntactically valid JSON).
    """

    brand_name: str | None = Field(
        default=None,
        description=(
            "Brand name as featured on the label — usually the most prominent text on the front label, "
            "e.g. 'OLD TOM DISTILLERY'. Never take it from the name-and-address statement."
        ),
    )
    fanciful_name: str | None = Field(
        default=None,
        description=(
            "A separate marketing/product name distinct from the brand name and from the class/type "
            "designation (e.g. a proprietary blend name). Usually null — most labels don't have one."
        ),
    )
    class_type: str | None = Field(
        default=None,
        description=(
            "The standards-of-identity designation describing what kind of product this is, e.g. "
            "'Kentucky Straight Bourbon Whiskey' or 'Cabernet Sauvignon'. Not the alcohol content and not the brand name."
        ),
    )
    abv_percent: float | None = Field(
        default=None,
        description="Alcohol content as a bare number, percent by volume, e.g. 45.0 for '45% Alc./Vol.'",
    )
    proof: float | None = Field(
        default=None,
        description="Proof as a bare number if a proof statement is printed, e.g. 90 for '90 Proof'. Usually null.",
    )
    net_contents: str | None = Field(default=None, description="Net contents as printed, e.g. '750 mL'")
    name_address: str | None = Field(
        default=None,
        description=(
            "The complete bottler/producer/importer name-and-address statement, verbatim and in full, joining "
            "all of its lines — including the company name it starts with, e.g. 'Maison Duval, Imported by "
            "Coastal Wines, Boston, MA' or 'Bottled by Old Mill Distilling Co., Frankfort, KY'."
        ),
    )
    country_of_origin: str | None = Field(
        default=None,
        description=(
            "Country of origin statement, if present, e.g. 'Product of France'. Only an explicit "
            "statement of where the product was made — never a city or state taken from a bottler's "
            "or importer's address."
        ),
    )
    appellation: str | None = Field(default=None, description="Appellation of origin, if present (wine)")
    sulfite_declaration: str | None = Field(default=None, description="Sulfite declaration text, if present (wine)")
    government_warning_text: str | None = Field(
        default=None,
        description=(
            "Verbatim transcription of the ENTIRE Government Warning statement, preserving capitalization "
            "exactly as printed. Only if a warning paragraph is actually printed on this label — usually a "
            "boxed paragraph on the back label; most front labels have none, and then this is null."
        ),
    )
    other_disclosures: list[str] = Field(
        default_factory=list,
        description=(
            "Any other commodity-specific disclosures noticed (e.g. color additive, FD&C Yellow No. 5, "
            "aspartame) not covered by the fields above"
        ),
    )
    illegible_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Names of the fields above (using their exact field names, e.g. 'net_contents') that could "
            "not be read with confidence, rather than guessed"
        ),
    )


class ExtractionOut(BaseModel):
    """Status of one label image's background extraction."""

    id: str
    status: Literal["pending", "done", "error", "cancelled"]
    error_message: str | None = None
    latency_ms: int | None = None
    extracted_fields: ExtractedLabelFields | None = None

    model_config = {"from_attributes": True}


class DecisionIn(BaseModel):
    decision: Literal["accept", "reject", "follow_up"]
    note: str | None = None


class DecisionOut(DecisionIn):
    decided_at: datetime

    model_config = {"from_attributes": True}


class FieldComparisonOut(BaseModel):
    field_name: str
    application_value: str | None
    extracted_value: str | None
    match_type: str
    status: str
    detail: str | None

    model_config = {"from_attributes": True}


class ReviewResult(BaseModel):
    application: ApplicationOut
    front_extraction_id: str
    back_extraction_id: str | None
    extracted_fields: ExtractedLabelFields
    field_sources: dict[str, Literal["front", "back"]]
    comparisons: list[FieldComparisonOut]
    model_used: str
    latency_ms: int  # time the user waited after submitting
    extraction_ms: int  # time the model spent reading the label
    overall_status: str  # "clear" | "flagged"
    decision: DecisionOut | None = None


class BatchItemOut(BaseModel):
    application_id: str
    status: str
    error_message: str | None
    result: ReviewResult | None = None


class BatchSummary(BaseModel):
    id: str
    created_at: datetime
    total: int
    done: int
    errored: int
    items: list[BatchItemOut]
