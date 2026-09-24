"""Batch review: group several application+label reviews under one batch id
so the frontend can show a combined summary. Deliberately simple —
synchronous, in-request processing per item, no job queue. Practical for the
tens-of-labels case, not a 200-300-at-once import scenario; that gap is a
documented limitation rather than infrastructure we don't have time to build
and test properly.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Application, BatchItem, ReviewBatch
from app.review_service import ExtractionFailedError, build_review_result, create_application, latest_review_run, run_review
from app.routers.forms import declared_application_form, resolve_label_image
from app.schemas import ApplicationIn, BatchItemOut, BatchSummary

router = APIRouter(prefix="/batches", tags=["batches"])


@router.post("", response_model=BatchSummary)
def create_batch(db: Session = Depends(get_db)) -> BatchSummary:
    batch = ReviewBatch()
    db.add(batch)
    db.commit()
    return _summarize(db, batch)


@router.post("/{batch_id}/items", response_model=BatchItemOut)
async def add_batch_item(
    batch_id: str,
    front: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    front_extraction_id: str | None = Form(None),
    back_extraction_id: str | None = Form(None),
    declared: ApplicationIn = Depends(declared_application_form),
    db: Session = Depends(get_db),
) -> BatchItemOut:
    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No batch with that id.")

    started = time.monotonic()
    front_id = await resolve_label_image(db, side="front", file=front, extraction_id=front_extraction_id, required=True)
    back_id = await resolve_label_image(db, side="back", file=back, extraction_id=back_extraction_id, required=False)

    application = create_application(db, declared, front_extraction_id=front_id, back_extraction_id=back_id)
    item = BatchItem(batch_id=batch_id, application_id=application.id, status="pending")
    db.add(item)
    db.commit()

    try:
        result = await run_review(db, application, started=started)
        item.status = "done"
        db.commit()
        return BatchItemOut(application_id=application.id, status="done", error_message=None, result=result)
    except ExtractionFailedError as exc:
        item.status = "error"
        item.error_message = str(exc)
        db.commit()
        return BatchItemOut(application_id=application.id, status="error", error_message=str(exc), result=None)


@router.get("/{batch_id}", response_model=BatchSummary)
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> BatchSummary:
    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No batch with that id.")
    return _summarize(db, batch)


def _summarize(db: Session, batch: ReviewBatch) -> BatchSummary:
    items: list[BatchItemOut] = []
    for item in batch.items:
        result = None
        if item.status == "done":
            application = db.get(Application, item.application_id)
            run = latest_review_run(db, item.application_id)
            if application is not None and run is not None:
                result = build_review_result(application, run)
        items.append(
            BatchItemOut(application_id=item.application_id, status=item.status, error_message=item.error_message, result=result)
        )

    return BatchSummary(
        id=batch.id,
        created_at=batch.created_at,
        total=len(items),
        done=sum(1 for i in items if i.status == "done"),
        errored=sum(1 for i in items if i.status == "error"),
        items=items,
    )
