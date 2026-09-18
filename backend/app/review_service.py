"""Orchestrates one end-to-end review: create the application record, extract
fields from the label image(s), compare them against what was declared, and
persist all of it. Shared by the single-review and batch endpoints so there's
exactly one place that defines what "reviewing a label" means.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.inference.ollama_client import extract_label_fields
from app.matching.engine import MATCH, compare
from app.models import Application, ExtractionResult, FieldComparison
from app.schemas import ApplicationIn, ApplicationOut, ExtractedLabelFields, FieldComparisonOut, ReviewResult
from app.storage import save_label_image_record


def create_application_with_images(
    db: Session,
    data: ApplicationIn,
    *,
    front_bytes: bytes,
    front_content_type: str,
    back_bytes: bytes | None,
    back_content_type: str | None,
) -> Application:
    """Persists the declared application fields and its label image(s)."""

    application = Application(**data.model_dump())
    db.add(application)
    db.flush()  # assigns application.id without committing yet

    save_label_image_record(db, application.id, "front", front_bytes, front_content_type)
    if back_bytes is not None:
        save_label_image_record(db, application.id, "back", back_bytes, back_content_type or "image/jpeg")

    return application


async def run_review(db: Session, application: Application, front_image: bytes, back_image: bytes | None) -> ReviewResult:
    extracted, latency_ms = await extract_label_fields(
        front_image=front_image,
        back_image=back_image,
        beverage_class=application.beverage_class,
        imported=application.imported,
    )

    extraction = ExtractionResult(
        application_id=application.id,
        extracted_fields=extracted.model_dump(),
        model_used="ollama",  # the specific model name lives in settings; kept generic here
        latency_ms=latency_ms,
    )
    db.add(extraction)
    db.flush()  # assigns extraction.id without committing yet

    verdicts = compare(_to_application_in(application), extracted)
    db.add_all(
        FieldComparison(
            extraction_result_id=extraction.id,
            field_name=v.field_name,
            application_value=v.application_value,
            extracted_value=v.extracted_value,
            match_type=v.match_type,
            status=v.status,
            detail=v.detail,
        )
        for v in verdicts
    )
    db.commit()

    return build_review_result(application, extraction)


def build_review_result(application: Application, extraction: ExtractionResult) -> ReviewResult:
    """Assembles the API response shape from a persisted application + its
    extraction (and, via the relationship, comparisons). Used both right
    after a fresh review and when re-fetching a stored one."""

    comparisons = extraction.comparisons
    overall_status = "clear" if all(c.status == MATCH for c in comparisons) else "flagged"
    return ReviewResult(
        application=ApplicationOut.model_validate(application),
        extracted_fields=ExtractedLabelFields.model_validate(extraction.extracted_fields),
        comparisons=[FieldComparisonOut.model_validate(c) for c in comparisons],
        model_used=extraction.model_used,
        latency_ms=extraction.latency_ms,
        overall_status=overall_status,
    )


def _to_application_in(application: Application) -> ApplicationIn:
    return ApplicationIn.model_validate(application, from_attributes=True)
