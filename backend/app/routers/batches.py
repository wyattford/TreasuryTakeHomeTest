"""Batch review endpoints. The flow, driven by the frontend's batch page:

1. POST /batches with every row of the spreadsheet (declared fields + image
   filenames). Rows start out "awaiting_images".
2. For each row: upload its image(s) with POST /extractions?priority=batch —
   reading starts right away — then PUT .../items/{id}/images to attach the
   extraction ids. The row is queued and the batch's background runner
   reviews it (app/batch_service.py).
3. Poll GET /batches/{id} for progress; open individual results with
   GET /reviews/{application_id} and record decisions with
   PUT /reviews/{application_id}/decision, exactly as for a single review.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app import batch_service
from app.batch_service import BatchError
from app.db import get_db
from app.models import BatchItem, ReviewBatch
from app.schemas import AttachImagesIn, BatchCreateIn, BatchItemOut, BatchOut, BatchSummaryOut

router = APIRouter(prefix="/batches", tags=["batches"])

_RECENT_BATCHES = 20


def _get_batch(db: Session, batch_id: str) -> ReviewBatch:
    batch = db.get(ReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No batch with that id.")
    return batch


@router.post("", response_model=BatchOut, status_code=201)
def create_batch(body: BatchCreateIn, db: Session = Depends(get_db)) -> BatchOut:
    """Creates the batch with all of its rows, before any images are sent,
    so an interrupted upload can be picked up again."""

    return batch_service.batch_out(db, batch_service.create_batch(db, body))


@router.get("", response_model=list[BatchSummaryOut])
def list_batches(db: Session = Depends(get_db)) -> list[BatchSummaryOut]:
    batches = db.query(ReviewBatch).order_by(ReviewBatch.created_at.desc()).limit(_RECENT_BATCHES)
    return [batch_service.batch_summary(db, batch) for batch in batches]


@router.get("/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: str, db: Session = Depends(get_db)) -> BatchOut:
    return batch_service.batch_out(db, _get_batch(db, batch_id))


# async so it runs on the event loop alongside the batch runner — see
# batch_service.ensure_runner for why that ordering matters.
@router.put("/{batch_id}/items/{item_id}/images", response_model=BatchItemOut)
async def attach_images(batch_id: str, item_id: str, body: AttachImagesIn, db: Session = Depends(get_db)) -> BatchItemOut:
    batch = _get_batch(db, batch_id)
    item = db.get(BatchItem, item_id)
    if item is None or item.batch_id != batch_id:
        raise HTTPException(status_code=404, detail="No row with that id in this batch.")
    try:
        batch_service.attach_images(db, batch, item, body.front_extraction_id, body.back_extraction_id)
    except BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return next(i for i in batch_service.batch_items(db, batch) if i.id == item_id)


# async: cancelling asyncio tasks must happen on the event loop's thread,
# not in the worker thread FastAPI runs plain `def` endpoints in.
@router.post("/{batch_id}/cancel", response_model=BatchOut)
async def cancel_batch(batch_id: str, db: Session = Depends(get_db)) -> BatchOut:
    batch = _get_batch(db, batch_id)
    batch_service.cancel_batch(db, batch)
    return batch_service.batch_out(db, batch)


@router.post("/{batch_id}/retry-failed", response_model=BatchOut)
async def retry_failed(batch_id: str, db: Session = Depends(get_db)) -> BatchOut:
    batch = _get_batch(db, batch_id)
    try:
        batch_service.retry_failed(db, batch)
    except BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return batch_service.batch_out(db, batch)


@router.get("/{batch_id}/export.csv")
def export_batch(batch_id: str, db: Session = Depends(get_db)) -> Response:
    batch = _get_batch(db, batch_id)
    filename = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in batch.name)[:60] or "batch"
    return Response(
        content=batch_service.export_csv(db, batch),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}-results.csv"'},
    )
