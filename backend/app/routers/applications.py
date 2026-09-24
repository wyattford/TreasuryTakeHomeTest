"""Optional convenience endpoint: read a filled-in TTB F 5100.31 PDF and
return whatever application fields it captures, so the frontend can
pre-fill its form instead of the user retyping everything by hand."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.application_pdf import ApplicationPdfError, extract_application_pdf_fields
from app.routers.forms import read_upload
from app.schemas import ExtractedApplicationFields

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("/extract-pdf", response_model=ExtractedApplicationFields)
async def extract_pdf(file: UploadFile = File(...)) -> ExtractedApplicationFields:
    pdf_bytes = await read_upload(file)
    try:
        # pypdf's parsing is synchronous CPU work; run it off the event loop
        # so it doesn't stall other requests (reviews, batches) for its duration.
        fields = await run_in_threadpool(extract_application_pdf_fields, pdf_bytes)
    except ApplicationPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ExtractedApplicationFields(**fields)
