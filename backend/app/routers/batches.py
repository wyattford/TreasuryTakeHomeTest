"""Batch review: group several application+label reviews under one batch id
so the frontend can show a combined summary. Deliberately simple —
synchronous, in-request processing per item, no job queue. Practical for the
tens-of-labels case, not a 200-300-at-once import scenario; that gap is a
documented limitation rather than infrastructure we don't have time to build
and test properly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.data.ttb_rules import BeverageClass
from app.db import get_db
from app.inference.ollama_client import OllamaUnavailableError
from app.models import Application, BatchItem, ExtractionResult, ReviewBatch
from app.review_service import build_review_result, create_application_with_images, run_review
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
    front: UploadFile = File(...),
    back: UploadFile | None = File(None),
    beverage_class: BeverageClass = Form(...),
    imported: bool = Form(False),
    brand_name: str = Form(...),
    fanciful_name: str | None = Form(None),
    class_type: str = Form(...),
    abv: float | None = Form(None),
    net_contents: str = Form(...),
    name_address: str = Form(...),
    country_of_origin: str | None = Form(None),
    appellation: str | None = Form(None),
    sulfite_declaration: str | None = Form(None),
    db: Session = Depends(get_db),
) -> BatchItemOut:
    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No batch with that id.")

    front_bytes = await front.read()
    back_bytes = await back.read() if back is not None else None

    application = create_application_with_images(
        db,
        ApplicationIn(
            beverage_class=beverage_class,
            imported=imported,
            brand_name=brand_name,
            fanciful_name=fanciful_name,
            class_type=class_type,
            abv=abv,
            net_contents=net_contents,
            name_address=name_address,
            country_of_origin=country_of_origin,
            appellation=appellation,
            sulfite_declaration=sulfite_declaration,
        ),
        front_bytes=front_bytes,
        front_content_type=front.content_type or "image/jpeg",
        back_bytes=back_bytes,
        back_content_type=back.content_type if back else None,
    )

    item = BatchItem(batch_id=batch_id, application_id=application.id, status="pending")
    db.add(item)
    db.commit()

    try:
        result = await run_review(db, application, front_bytes, back_bytes)
        item.status = "done"
        db.commit()
        return BatchItemOut(application_id=application.id, status="done", error_message=None, result=result)
    except OllamaUnavailableError as exc:
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
            extraction = (
                db.query(ExtractionResult)
                .filter(ExtractionResult.application_id == item.application_id)
                .order_by(ExtractionResult.created_at.desc())
                .first()
            )
            if application is not None and extraction is not None:
                result = build_review_result(application, extraction)
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
