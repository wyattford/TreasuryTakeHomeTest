"""Request-parsing pieces shared by the review and batch endpoints: size-
limited upload reading, the declared-application form fields, and resolving
a label image that arrives either as a file or as an already-started
extraction."""

from __future__ import annotations

from fastapi import Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.data.ttb_rules import BeverageClass
from app.extraction_service import start_extraction
from app.images import InvalidImageError
from app.models import ImageExtraction
from app.schemas import ApplicationIn

_READ_CHUNK_BYTES = 1024 * 1024


async def read_upload(file: UploadFile) -> bytes:
    """Reads an upload, refusing it with a 413 as soon as it exceeds
    ``settings.max_upload_bytes`` rather than after buffering all of it."""

    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > settings.max_upload_bytes:
            limit_mb = settings.max_upload_bytes // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"{file.filename or 'That file'} is larger than the {limit_mb} MB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


async def start_extraction_from_upload(db: Session, file: UploadFile) -> ImageExtraction:
    try:
        return await start_extraction(db, await read_upload(file))
    except InvalidImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def resolve_label_image(
    db: Session, *, side: str, file: UploadFile | None, extraction_id: str | None, required: bool
) -> str | None:
    """Returns the extraction id for one side of the label. The frontend
    normally uploads each image as soon as it's chosen (so extraction runs
    while the form is filled in) and passes the resulting id here; sending the
    file itself with the review also works, it's just slower."""

    if file is not None and extraction_id:
        raise HTTPException(status_code=422, detail=f"Send either a {side} image or a {side}_extraction_id, not both.")
    if extraction_id:
        if db.get(ImageExtraction, extraction_id) is None:
            raise HTTPException(status_code=404, detail=f"No uploaded {side} image with that id — please upload it again.")
        return extraction_id
    if file is not None:
        return (await start_extraction_from_upload(db, file)).id
    if required:
        raise HTTPException(status_code=422, detail=f"A {side} label image is required.")
    return None


def _blank_to_none(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


def declared_application_form(
    beverage_class: BeverageClass = Form(...),
    imported: bool = Form(False),
    brand_name: str | None = Form(None),
    fanciful_name: str | None = Form(None),
    class_type: str | None = Form(None),
    abv: float | None = Form(None),
    net_contents: str | None = Form(None),
    name_address: str | None = Form(None),
    country_of_origin: str | None = Form(None),
    appellation: str | None = Form(None),
    sulfite_declaration: str | None = Form(None),
) -> ApplicationIn:
    """The TTB F 5100.31 fields, as a FastAPI dependency. Only beverage class
    is required; blank text fields are treated as not declared."""

    return ApplicationIn(
        beverage_class=beverage_class,
        imported=imported,
        brand_name=_blank_to_none(brand_name),
        fanciful_name=_blank_to_none(fanciful_name),
        class_type=_blank_to_none(class_type),
        abv=abv,
        net_contents=_blank_to_none(net_contents),
        name_address=_blank_to_none(name_address),
        country_of_origin=_blank_to_none(country_of_origin),
        appellation=_blank_to_none(appellation),
        sulfite_declaration=_blank_to_none(sulfite_declaration),
    )
