"""Background label extraction: start reading an image the moment it's
uploaded, and let a later review pick up the result.

The point is latency the user never sees. The vision model takes several
seconds per image; an agent takes longer than that to type in the
application fields. Starting extraction on upload means that by the time
"Review" is pressed, the label has usually already been read and the review
is just the (instant) matching step.

Tasks live in this process's memory (one uvicorn worker). If the process
restarts mid-extraction, the row is left "pending" with no task behind it;
anything that waits on it notices and re-runs it from the stored image.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.images import NORMALIZED_CONTENT_TYPE, normalize_label_image
from app.inference.ollama_client import EXTRACTION_SYSTEM_PROMPT, OllamaUnavailableError, extract_label_fields
from app.models import ImageExtraction
from app.priority_gate import BATCH, INTERACTIVE, PriorityGate
from app.storage import image_path, save_image

PENDING = "pending"
DONE = "done"
ERROR = "error"
CANCELLED = "cancelled"

PRIORITIES = {"interactive": INTERACTIVE, "batch": BATCH}

_tasks: dict[str, asyncio.Task] = {}
_ollama_gate: PriorityGate | None = None


class ExtractionNotFoundError(LookupError):
    pass


def _gate() -> PriorityGate:
    # Created lazily so it binds to the running event loop.
    global _ollama_gate
    if _ollama_gate is None:
        _ollama_gate = PriorityGate(settings.ollama_max_concurrency)
    return _ollama_gate


async def start_extraction(db: Session, raw_image: bytes, *, priority: str = "interactive") -> ImageExtraction:
    """Normalizes and stores the image, then starts extracting it in the
    background. Returns immediately. Raises InvalidImageError for a file that
    isn't a readable image.

    ``priority`` is "interactive" (an agent is waiting on this image) or
    "batch"; interactive extractions always get the next free model slot.

    Re-uploading an identical image reuses the earlier result (or the
    extraction already in flight) instead of running the model again."""

    image = await run_in_threadpool(normalize_label_image, raw_image)
    cache_key = _cache_key(image)

    reusable = (
        db.query(ImageExtraction)
        .filter(ImageExtraction.cache_key == cache_key, ImageExtraction.status.in_([DONE, PENDING]))
        .order_by(ImageExtraction.created_at.desc())
        .all()
    )
    for record in reusable:
        if record.status == DONE or record.id in _tasks:
            return record

    record = ImageExtraction(
        file_path=save_image(image, NORMALIZED_CONTENT_TYPE),
        content_type=NORMALIZED_CONTENT_TYPE,
        cache_key=cache_key,
        status=PENDING,
        priority=priority,
        model_used=settings.ollama_model,
    )
    db.add(record)
    db.commit()
    _schedule(record.id, image, record.priority)
    return record


async def wait_for_extraction(
    db: Session, extraction_id: str, *, timeout: float | None = None, retry_failed: bool = False
) -> ImageExtraction:
    """Waits (up to ``timeout`` seconds, or until finished if None) for an
    extraction and returns its current record, finished or not.

    ``retry_failed`` re-runs an extraction that previously errored or was
    cancelled — used when a review actually needs the result, e.g. if Ollama
    was briefly down when the image was first uploaded.

    Commits the session's current transaction before waiting, so callers
    must not have changes pending that they don't mean to commit."""

    record = db.get(ImageExtraction, extraction_id)
    if record is None:
        raise ExtractionNotFoundError(extraction_id)

    needs_run = (record.status == PENDING and extraction_id not in _tasks) or (
        retry_failed and record.status in (ERROR, CANCELLED)
    )
    if needs_run:
        record.status = PENDING
        record.error_message = None
        db.commit()
        _schedule(extraction_id, image_path(record.file_path).read_bytes(), record.priority)

    task = _tasks.get(extraction_id)
    if task is not None:
        # Hand the session's pooled connection back for the wait, which can
        # be minutes long behind a batch. Holding it would let enough waiters
        # (a big batch, many long-polls) drain the pool, and the next
        # checkout would then block the event loop the waiters need.
        db.commit()
        # asyncio.wait (unlike wait_for) never cancels the task when the
        # caller gives up — someone else may still be waiting on it — and
        # doesn't raise if the task itself was cancelled.
        await asyncio.wait({task}, timeout=timeout)

    db.refresh(record)
    return record


def cancel_extraction(extraction_id: str) -> None:
    """Stops an in-flight extraction, e.g. because the user swapped the photo
    for a different one. No-op if it has already finished."""

    task = _tasks.get(extraction_id)
    if task is not None:
        task.cancel()


def _cache_key(image: bytes) -> str:
    digest = hashlib.sha256(image)
    digest.update(settings.ollama_model.encode())
    digest.update(EXTRACTION_SYSTEM_PROMPT.encode())
    return digest.hexdigest()


def _schedule(extraction_id: str, image: bytes, priority: str) -> None:
    task = asyncio.create_task(_run(extraction_id, image, PRIORITIES[priority]))
    _tasks[extraction_id] = task
    task.add_done_callback(lambda _: _tasks.pop(extraction_id, None))


async def _run(extraction_id: str, image: bytes, priority: int) -> None:
    fields = None
    latency_ms = None
    error = None
    try:
        async with _gate().slot(priority):
            fields, latency_ms = await extract_label_fields(image)
        status = DONE
    except OllamaUnavailableError as exc:
        status, error = ERROR, str(exc)
    except asyncio.CancelledError:
        _finish(extraction_id, CANCELLED, None, None, "Cancelled before it finished.")
        raise
    _finish(extraction_id, status, fields.model_dump() if fields else None, latency_ms, error)


def _finish(extraction_id: str, status: str, fields: dict | None, latency_ms: int | None, error: str | None) -> None:
    with SessionLocal() as db:
        record = db.get(ImageExtraction, extraction_id)
        if record is None:
            return
        record.status = status
        record.extracted_fields = fields
        record.latency_ms = latency_ms
        record.error_message = error
        record.completed_at = datetime.now(UTC)
        db.commit()
