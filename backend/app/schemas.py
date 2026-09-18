from datetime import datetime

from pydantic import BaseModel, Field

from app.data.ttb_rules import BeverageClass


class ApplicationIn(BaseModel):
    """What an applicant declares on TTB F 5100.31 — submitted alongside the
    label image(s) so we have something to check the label against."""

    beverage_class: BeverageClass
    imported: bool = False
    brand_name: str
    fanciful_name: str | None = None
    class_type: str
    abv: float | None = None
    net_contents: str
    name_address: str
    country_of_origin: str | None = None
    appellation: str | None = None
    sulfite_declaration: str | None = None


class ApplicationOut(ApplicationIn):
    id: str
    submitted_at: datetime

    model_config = {"from_attributes": True}


class ExtractedLabelFields(BaseModel):
    """The JSON shape we ask the vision model to fill in.

    Sent to Ollama as a schema described in the prompt text (NOT via Ollama's
    `format`/grammar-constrained decoding — see the note in
    app/inference/ollama_client.py on why that mechanism was dropped after
    live testing showed it silently drops and misassigns fields with this
    model, even though it mechanically guarantees syntactically valid JSON).
    """

    brand_name: str | None = Field(
        default=None,
        description="Brand name as printed on the label — the main product/producer name, e.g. 'OLD TOM DISTILLERY'",
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
    net_contents: str | None = Field(default=None, description="Net contents as printed, e.g. '750 mL'")
    name_address: str | None = Field(default=None, description="Bottler/producer/importer name and address statement")
    country_of_origin: str | None = Field(
        default=None,
        description=(
            "Country of origin statement, if present. Leave null for a domestic (non-imported) "
            "product even if the label mentions a US state or city."
        ),
    )
    appellation: str | None = Field(default=None, description="Appellation of origin, if present (wine)")
    sulfite_declaration: str | None = Field(default=None, description="Sulfite declaration text, if present (wine)")
    government_warning_text: str | None = Field(
        default=None,
        description=(
            "Verbatim transcription of the ENTIRE Government Warning statement, starting with the "
            "words 'GOVERNMENT WARNING:' and preserving capitalization"
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
    extracted_fields: ExtractedLabelFields
    comparisons: list[FieldComparisonOut]
    model_used: str
    latency_ms: int
    overall_status: str  # "clear" | "flagged"


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
