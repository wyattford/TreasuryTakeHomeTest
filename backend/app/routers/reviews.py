import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Application, ReviewDecision
from app.review_service import (
    ExtractionFailedError,
    build_review_result,
    create_application,
    latest_review_run,
    run_review,
)
from app.routers.forms import declared_application_form, resolve_label_image
from app.schemas import ApplicationIn, DecisionIn, DecisionOut, ReviewResult

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewResult)
async def create_review(
    front: UploadFile | None = File(None),
    back: UploadFile | None = File(None),
    front_extraction_id: str | None = Form(None),
    back_extraction_id: str | None = Form(None),
    declared: ApplicationIn = Depends(declared_application_form),
    db: Session = Depends(get_db),
) -> ReviewResult:
    """Reviews a label against the declared application fields. Each label
    image is given either as an extraction id from POST /extractions (the
    fast path — it's usually already been read) or as a file."""

    started = time.monotonic()
    front_id = await resolve_label_image(db, side="front", file=front, extraction_id=front_extraction_id, required=True)
    back_id = await resolve_label_image(db, side="back", file=back, extraction_id=back_extraction_id, required=False)

    application = create_application(db, declared, front_extraction_id=front_id, back_extraction_id=back_id)
    db.commit()

    try:
        return await run_review(db, application, started=started)
    except ExtractionFailedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{application_id}", response_model=ReviewResult)
def get_review(application_id: str, db: Session = Depends(get_db)) -> ReviewResult:
    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="No application with that id.")

    run = latest_review_run(db, application_id)
    if run is None:
        raise HTTPException(status_code=404, detail="That application hasn't been reviewed yet.")

    return build_review_result(application, run)


@router.put("/{application_id}/decision", response_model=DecisionOut)
def set_decision(application_id: str, body: DecisionIn, db: Session = Depends(get_db)) -> DecisionOut:
    """Records the agent's call (accept / reject / needs follow-up). Setting
    it again replaces the earlier decision."""

    application = db.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="No application with that id.")

    decision = application.decision or ReviewDecision(application_id=application_id)
    decision.decision = body.decision
    decision.note = (body.note or "").strip() or None
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return DecisionOut.model_validate(decision)
