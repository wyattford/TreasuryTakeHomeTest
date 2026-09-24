"""Label image upload + background extraction.

The frontend uploads each label image the moment the user picks it, gets an
extraction id back immediately, and passes that id to POST /reviews later.
The model reads the label while the user is still typing in the application
fields, so the review itself is near-instant.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.extraction_service import ExtractionNotFoundError, cancel_extraction, wait_for_extraction
from app.models import ImageExtraction
from app.routers.forms import start_extraction_from_upload
from app.schemas import ExtractionOut
from app.storage import image_path

router = APIRouter(prefix="/extractions", tags=["extractions"])

MAX_WAIT_SECONDS = 30


@router.post("", response_model=ExtractionOut, status_code=202)
async def create_extraction(image: UploadFile = File(...), db: Session = Depends(get_db)) -> ExtractionOut:
    """Stores the image and starts reading it in the background. Returns
    right away with status "pending" (or "done", if this exact image was
    already read before)."""

    return ExtractionOut.model_validate(await start_extraction_from_upload(db, image))


@router.get("/{extraction_id}", response_model=ExtractionOut)
async def get_extraction(
    extraction_id: str,
    wait: float = Query(0, ge=0, le=MAX_WAIT_SECONDS, description="Seconds to wait for it to finish before responding."),
    db: Session = Depends(get_db),
) -> ExtractionOut:
    """Current status. With ``wait``, long-polls: responds as soon as the
    extraction finishes, or after ``wait`` seconds with it still pending."""

    try:
        record = await wait_for_extraction(db, extraction_id, timeout=wait)
    except ExtractionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No uploaded image with that id.") from exc
    return ExtractionOut.model_validate(record)


@router.delete("/{extraction_id}", status_code=204)
def delete_extraction(extraction_id: str) -> Response:
    """Stops an in-flight extraction the user no longer needs (they picked a
    different photo), freeing the model for the one they do."""

    cancel_extraction(extraction_id)
    return Response(status_code=204)


@router.get("/{extraction_id}/image")
def get_extraction_image(extraction_id: str, db: Session = Depends(get_db)) -> FileResponse:
    """The image exactly as the model saw it (upright, resized)."""

    record = db.get(ImageExtraction, extraction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No uploaded image with that id.")
    return FileResponse(image_path(record.file_path), media_type=record.content_type)
