"""Batch review: a few hundred applications submitted together and reviewed
in the background.

The browser creates the batch with every row up front (so an interrupted
upload can be resumed), then uploads each label image through the normal
POST /extractions path — reading starts during the upload — and attaches the
resulting extraction ids to its row. A per-batch runner task picks up rows
as their images arrive and reviews them with the same ``run_review`` a
single review uses; there's no second copy of the review logic.

Like extraction, runners live in this process (one uvicorn worker). All
batch state is in the database, so ``resume_batches`` restarts them after a
restart and nothing is lost but time.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.extraction_service import cancel_extraction
from app.matching.engine import MATCH
from app.models import Application, BatchItem, ImageExtraction, ReviewBatch, ReviewRun
from app.review_service import ExtractionFailedError, create_application, run_review
from app.schemas import (
    ApplicationIn,
    BatchCounts,
    BatchCreateIn,
    BatchItemOut,
    BatchOut,
    BatchSummaryOut,
    DecisionOut,
)

AWAITING_IMAGES = "awaiting_images"
QUEUED = "queued"
REVIEWED = "reviewed"
ERROR = "error"
SKIPPED = "skipped"

# Reviews waiting on their extractions at once, per batch. Reviews mostly
# just wait; the real limit on model work is the extraction PriorityGate.
_REVIEW_CONCURRENCY = 16
# How often a running batch checks for rows whose images have just arrived.
_POLL_SECONDS = 1.0

_runners: dict[str, asyncio.Task] = {}

logger = logging.getLogger(__name__)

_REVIEW_FAILED = "Something went wrong reviewing this application. Please try it again."


class BatchError(ValueError):
    """A request that doesn't fit the batch's current state."""


def create_batch(db: Session, data: BatchCreateIn) -> ReviewBatch:
    batch = ReviewBatch(name=data.name.strip())
    db.add(batch)
    db.flush()
    for number, row in enumerate(data.rows, start=1):
        declared = ApplicationIn.model_validate(row.model_dump(include=set(ApplicationIn.model_fields)))
        db.add(
            BatchItem(
                batch_id=batch.id,
                row_number=number,
                reference=(row.reference or "").strip() or None,
                declared=declared.model_dump(mode="json"),
                front_image_name=row.front_image,
                back_image_name=row.back_image or None,
                status=AWAITING_IMAGES,
            )
        )
    db.commit()
    db.refresh(batch)
    return batch


def attach_images(db: Session, batch: ReviewBatch, item: BatchItem, front_id: str, back_id: str | None) -> BatchItem:
    """Records an uploaded row's images and queues it for review."""

    if batch.cancelled_at is not None:
        raise BatchError("This batch was cancelled.")
    if item.status not in (AWAITING_IMAGES, ERROR):
        raise BatchError("This row already has its images.")
    if bool(back_id) != bool(item.back_image_name):
        raise BatchError("This row's back image doesn't match the spreadsheet (missing or unexpected).")
    for extraction_id in filter(None, (front_id, back_id)):
        if db.get(ImageExtraction, extraction_id) is None:
            raise BatchError(f"No uploaded image with id {extraction_id}.")

    item.front_extraction_id = front_id
    item.back_extraction_id = back_id
    item.application_id = None  # new images, new review
    item.status = QUEUED
    item.error_message = None
    if batch.started_at is None:
        batch.started_at = datetime.now(UTC)
    db.commit()
    ensure_runner(batch.id)
    return item


def cancel_batch(db: Session, batch: ReviewBatch) -> None:
    """Stops reviewing: rows not yet reviewed are skipped and their pending
    model work is dropped. Rows already reviewed keep their results."""

    batch.cancelled_at = datetime.now(UTC)
    for item in batch.items:
        if item.status in (AWAITING_IMAGES, QUEUED):
            item.status = SKIPPED
            for extraction_id in filter(None, (item.front_extraction_id, item.back_extraction_id)):
                record = db.get(ImageExtraction, extraction_id)
                # Only drop batch work; the same image might also be one an
                # agent is waiting on interactively.
                if record is not None and record.priority == "batch":
                    cancel_extraction(extraction_id)
    db.commit()


def retry_failed(db: Session, batch: ReviewBatch) -> int:
    if batch.cancelled_at is not None:
        raise BatchError("This batch was cancelled.")
    failed = [item for item in batch.items if item.status == ERROR and item.front_extraction_id]
    for item in failed:
        item.status = QUEUED
        item.error_message = None
    db.commit()
    if failed:
        ensure_runner(batch.id)
    return len(failed)


def ensure_runner(batch_id: str) -> None:
    runner = _runners.get(batch_id)
    # done() is already true once the runner has returned, even before its
    # done-callback removes it from _runners — so a row queued in that gap
    # still gets a fresh runner.
    if runner is not None and not runner.done():
        return
    task = asyncio.create_task(_run_batch(batch_id))
    _runners[batch_id] = task
    task.add_done_callback(lambda t: _runners.pop(batch_id, None) if _runners.get(batch_id) is t else None)


def resume_batches() -> None:
    """Restarts runners for batches that still had rows queued when the
    process last stopped."""

    with SessionLocal() as db:
        batch_ids = {
            batch_id
            for (batch_id,) in db.query(BatchItem.batch_id)
            .join(ReviewBatch)
            .filter(BatchItem.status == QUEUED, ReviewBatch.cancelled_at.is_(None))
            .distinct()
        }
    for batch_id in batch_ids:
        ensure_runner(batch_id)


async def _run_batch(batch_id: str) -> None:
    slots = asyncio.Semaphore(_REVIEW_CONCURRENCY)
    in_flight: dict[str, asyncio.Task] = {}
    while True:
        # No awaits between this check and returning: a row queued after it
        # is committed before ensure_runner() sees this task as done.
        with SessionLocal() as db:
            batch = db.get(ReviewBatch, batch_id)
            if batch is None or batch.cancelled_at is not None:
                queued = []
            else:
                queued = [
                    item_id
                    for (item_id,) in db.query(BatchItem.id)
                    .filter(BatchItem.batch_id == batch_id, BatchItem.status == QUEUED)
                    .order_by(BatchItem.row_number)
                    if item_id not in in_flight
                ]
        if not queued and not in_flight:
            return
        for item_id in queued:
            in_flight[item_id] = asyncio.create_task(_review_item(item_id, slots))
        done, _ = await asyncio.wait(in_flight.values(), timeout=_POLL_SECONDS, return_when=asyncio.FIRST_COMPLETED)
        for item_id in [item_id for item_id, task in in_flight.items() if task in done]:
            del in_flight[item_id]


async def _review_item(item_id: str, slots: asyncio.Semaphore) -> None:
    async with slots:
        with SessionLocal() as db:
            item = db.get(BatchItem, item_id)
            if item is None or item.status != QUEUED:
                return
            application = db.get(Application, item.application_id) if item.application_id else None
            if application is None:
                application = create_application(
                    db,
                    ApplicationIn.model_validate(item.declared),
                    front_extraction_id=item.front_extraction_id,
                    back_extraction_id=item.back_extraction_id,
                )
                item.application_id = application.id
                db.commit()
            try:
                await run_review(db, application)
                item.status = REVIEWED
            except ExtractionFailedError as exc:
                item.status = ERROR
                item.error_message = str(exc)
            except Exception:
                # Left "queued", the runner would pick this row up again every
                # second, forever, and the batch would never finish.
                logger.exception("Batch row %s failed unexpectedly", item_id)
                db.rollback()
                item = db.get(BatchItem, item_id)
                item.status = ERROR
                item.error_message = _REVIEW_FAILED
            db.commit()


# --- Read side: summaries and export ---


def batch_status(batch: ReviewBatch) -> str:
    statuses = {item.status for item in batch.items}
    if batch.cancelled_at is not None:
        return "cancelled"
    if AWAITING_IMAGES in statuses:
        return "uploading"
    if QUEUED in statuses:
        return "running"
    return "done"


def _latest_runs(db: Session, application_ids: list[str]) -> dict[str, ReviewRun]:
    runs: dict[str, ReviewRun] = {}
    if application_ids:
        for run in db.query(ReviewRun).filter(ReviewRun.application_id.in_(application_ids)).order_by(ReviewRun.created_at):
            runs[run.application_id] = run  # later runs overwrite earlier ones
    return runs


def _item_out(item: BatchItem, run: ReviewRun | None) -> BatchItemOut:
    attention = [c for c in run.comparisons if c.status != MATCH] if run else []
    brand = item.declared.get("brand_name") or (run.extracted_fields.get("brand_name") if run else None)
    decision = item.application.decision if item.application else None
    return BatchItemOut(
        id=item.id,
        row_number=item.row_number,
        reference=item.reference,
        front_image_name=item.front_image_name,
        back_image_name=item.back_image_name,
        status=item.status,
        error_message=item.error_message,
        front_extraction_id=item.front_extraction_id,
        back_extraction_id=item.back_extraction_id,
        application_id=item.application_id,
        brand_name=brand,
        overall_status=("flagged" if attention else "clear") if run and item.status == REVIEWED else None,
        attention_count=len(attention),
        decision=DecisionOut.model_validate(decision) if decision else None,
    )


def _counts(items: list[BatchItemOut]) -> BatchCounts:
    by_status = Counter(i.status for i in items)
    by_outcome = Counter(i.overall_status for i in items if i.overall_status)
    return BatchCounts(
        awaiting_images=by_status[AWAITING_IMAGES],
        queued=by_status[QUEUED],
        clear=by_outcome["clear"],
        flagged=by_outcome["flagged"],
        error=by_status[ERROR],
        skipped=by_status[SKIPPED],
        decided=sum(1 for i in items if i.decision is not None),
    )


def _eta_seconds(batch: ReviewBatch, counts: BatchCounts) -> int | None:
    finished = counts.clear + counts.flagged + counts.error
    remaining = counts.awaiting_images + counts.queued
    if batch.started_at is None or finished == 0 or remaining == 0 or batch.cancelled_at is not None:
        return None
    elapsed = (datetime.now(UTC) - batch.started_at).total_seconds()
    return round(elapsed / finished * remaining)


def batch_items(db: Session, batch: ReviewBatch) -> list[BatchItemOut]:
    runs = _latest_runs(db, [i.application_id for i in batch.items if i.application_id])
    return [_item_out(item, runs.get(item.application_id)) for item in batch.items]


def batch_out(db: Session, batch: ReviewBatch) -> BatchOut:
    items = batch_items(db, batch)
    counts = _counts(items)
    return BatchOut(
        id=batch.id,
        name=batch.name,
        created_at=batch.created_at,
        status=batch_status(batch),
        total=len(items),
        counts=counts,
        eta_seconds=_eta_seconds(batch, counts),
        items=items,
    )


def batch_summary(db: Session, batch: ReviewBatch) -> BatchSummaryOut:
    out = batch_out(db, batch)
    return BatchSummaryOut(**out.model_dump(exclude={"eta_seconds", "items"}))


_EXPORT_FIELDS = [
    "brand_name",
    "class_type",
    "abv",
    "proof",
    "net_contents",
    "name_address",
    "government_warning",
    "country_of_origin",
    "appellation",
    "sulfite_declaration",
]
_RESULT_LABELS = {"clear": "Everything checks out", "flagged": "Needs review"}
# A cell starting with one of these is run as a formula when the export is
# opened in Excel or Sheets, and references, filenames and notes come from
# importers and agents. A leading apostrophe makes the spreadsheet show it
# as plain text.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: object) -> object:
    return f"'{value}" if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES) else value


def export_csv(db: Session, batch: ReviewBatch) -> str:
    """One row per application: what was declared, each field's verdict,
    what needs attention, and the agent's decision."""

    runs = _latest_runs(db, [i.application_id for i in batch.items if i.application_id])
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["row", "reference", "front_image", "back_image", "result"]
        + [f"{field}_status" for field in _EXPORT_FIELDS]
        + ["needs_attention", "decision", "decision_note", "decided_at", "error", "application_id"]
    )
    for item in batch.items:
        run = runs.get(item.application_id)
        summary = _item_out(item, run)
        by_field = {c.field_name: c for c in run.comparisons} if run else {}
        if summary.overall_status:
            result = _RESULT_LABELS[summary.overall_status]
        else:
            result = {ERROR: "Couldn't be read", SKIPPED: "Skipped (batch cancelled)"}.get(item.status, "Not reviewed yet")
        attention = "; ".join(
            f"{c.field_name}: {c.status}" + (f" ({c.detail})" if c.detail else "")
            for c in (run.comparisons if run else [])
            if c.status != MATCH
        )
        decision = summary.decision
        row = (
            [item.row_number, item.reference or "", item.front_image_name, item.back_image_name or "", result]
            + [by_field[field].status if field in by_field else "" for field in _EXPORT_FIELDS]
            + [
                attention,
                decision.decision if decision else "",
                (decision.note or "") if decision else "",
                decision.decided_at.isoformat() if decision else "",
                item.error_message or "",
                item.application_id or "",
            ]
        )
        writer.writerow([_safe_cell(cell) for cell in row])
    return out.getvalue()
