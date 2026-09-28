"""Orchestrates one end-to-end review: wait for the label image(s) to finish
extracting (usually already done — extraction starts on upload), merge the
front and back readings, compare them against what was declared, and persist
all of it. Shared by the single-review and batch endpoints so there's exactly
one place that defines what "reviewing a label" means.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.config import settings
from app.extraction_service import DONE, wait_for_extraction
from app.matching.engine import MATCH, compare
from app.matching.merge import merge_extractions
from app.models import Application, FieldComparison, ImageExtraction, ReviewRun
from app.schemas import (
    ApplicationIn,
    ApplicationOut,
    DecisionOut,
    ExtractedLabelFields,
    FieldComparisonOut,
    ReviewResult,
)


class ExtractionFailedError(RuntimeError):
    """A label image couldn't be read (model unreachable, unusable response)."""


def create_application(
    db: Session, data: ApplicationIn, *, front_extraction_id: str, back_extraction_id: str | None
) -> Application:
    application = Application(**data.model_dump(), front_extraction_id=front_extraction_id, back_extraction_id=back_extraction_id)
    db.add(application)
    db.flush()  # assigns application.id without committing yet
    return application


async def run_review(db: Session, application: Application, *, started: float | None = None) -> ReviewResult:
    """``started`` is a time.monotonic() timestamp for when the user asked for
    the review, so the reported latency is what they actually waited."""

    started = time.monotonic() if started is None else started

    front = await _finished_extraction(db, application.front_extraction_id, "front")
    back = await _finished_extraction(db, application.back_extraction_id, "back") if application.back_extraction_id else None

    merged, sources = merge_extractions(
        ExtractedLabelFields.model_validate(front.extracted_fields),
        ExtractedLabelFields.model_validate(back.extracted_fields) if back else None,
    )
    verdicts = compare(ApplicationIn.model_validate(application, from_attributes=True), merged, sources)

    run = ReviewRun(
        application_id=application.id,
        extracted_fields=merged.model_dump(),
        field_sources=sources,
        model_used=settings.model_name,
        latency_ms=int((time.monotonic() - started) * 1000),
        extraction_ms=max(e.latency_ms or 0 for e in (front, back) if e is not None),
    )
    db.add(run)
    db.flush()  # assigns run.id without committing yet
    db.add_all(
        FieldComparison(
            review_run_id=run.id,
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

    return build_review_result(application, run)


async def _finished_extraction(db: Session, extraction_id: str, side: str) -> ImageExtraction:
    record = await wait_for_extraction(db, extraction_id, retry_failed=True)
    if record.status != DONE:
        raise ExtractionFailedError(f"Couldn't read the {side} label. {record.error_message or 'Please upload it again.'}")
    return record


def latest_review_run(db: Session, application_id: str) -> ReviewRun | None:
    return db.query(ReviewRun).filter(ReviewRun.application_id == application_id).order_by(ReviewRun.created_at.desc()).first()


def build_review_result(application: Application, run: ReviewRun) -> ReviewResult:
    """Assembles the API response shape from a persisted application + its
    review run (and, via the relationships, comparisons and decision). Used
    both right after a fresh review and when re-fetching a stored one."""

    comparisons = run.comparisons
    overall_status = "clear" if all(c.status == MATCH for c in comparisons) else "flagged"
    return ReviewResult(
        application=ApplicationOut.model_validate(application),
        front_extraction_id=application.front_extraction_id,
        back_extraction_id=application.back_extraction_id,
        extracted_fields=ExtractedLabelFields.model_validate(run.extracted_fields),
        field_sources=run.field_sources,
        comparisons=[FieldComparisonOut.model_validate(c) for c in comparisons],
        model_used=run.model_used,
        latency_ms=run.latency_ms,
        extraction_ms=run.extraction_ms,
        overall_status=overall_status,
        decision=DecisionOut.model_validate(application.decision) if application.decision else None,
    )
