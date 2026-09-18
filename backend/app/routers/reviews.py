from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.data.ttb_rules import BeverageClass
from app.db import get_db
from app.inference.ollama_client import OllamaUnavailableError
from app.models import Application, ExtractionResult
from app.review_service import build_review_result, create_application_with_images, run_review
from app.schemas import ApplicationIn, ReviewResult

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewResult)
async def create_review(
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
) -> ReviewResult:
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
    db.commit()

    try:
        return await run_review(db, application, front_bytes, back_bytes)
    except OllamaUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{application_id}", response_model=ReviewResult)
def get_review(application_id: str, db: Session = Depends(get_db)) -> ReviewResult:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="No application with that id.")

    extraction = (
        db.query(ExtractionResult)
        .filter(ExtractionResult.application_id == application_id)
        .order_by(ExtractionResult.created_at.desc())
        .first()
    )
    if extraction is None:
        raise HTTPException(status_code=404, detail="That application hasn't been reviewed yet.")

    return build_review_result(application, extraction)
