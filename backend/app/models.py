import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class ImageExtraction(Base):
    """One label image and the VLM's reading of it.

    Created the moment an image is uploaded — before the user has typed any
    application data — and filled in by a background task, so extraction runs
    while the user is still filling in the form. An image is extracted on its
    own (front and back separately), which also tells us which side of the
    container each field was printed on.
    """

    __tablename__ = "image_extractions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    # Hash of the normalized image + model + extraction prompt, so re-uploading
    # the same photo reuses the earlier result instead of running the model
    # again — but a changed model or prompt doesn't serve stale readings.
    cache_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending/done/error/cancelled
    extracted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # "interactive" (an agent is waiting) or "batch"; interactive work always
    # gets the next free model slot. Kept so a re-run keeps its place.
    priority: Mapped[str] = mapped_column(String, nullable=False, default="interactive")
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Application(Base):
    """Fields an applicant declares on TTB F 5100.31 (the COLA application) —
    what the label is checked *against*, not what's read off the image.

    Every declared text field is optional: with nothing declared, a review
    still checks the label on its own (required fields present, Government
    Warning exact, standard container size)."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    beverage_class: Mapped[str] = mapped_column(String, nullable=False)
    imported: Mapped[bool] = mapped_column(default=False)

    brand_name: Mapped[str | None] = mapped_column(String, nullable=True)
    fanciful_name: Mapped[str | None] = mapped_column(String, nullable=True)
    class_type: Mapped[str | None] = mapped_column(String, nullable=True)
    abv: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_contents: Mapped[str | None] = mapped_column(String, nullable=True)
    name_address: Mapped[str | None] = mapped_column(String, nullable=True)
    country_of_origin: Mapped[str | None] = mapped_column(String, nullable=True)
    appellation: Mapped[str | None] = mapped_column(String, nullable=True)
    sulfite_declaration: Mapped[str | None] = mapped_column(String, nullable=True)

    front_extraction_id: Mapped[str] = mapped_column(ForeignKey("image_extractions.id"), nullable=False)
    back_extraction_id: Mapped[str | None] = mapped_column(ForeignKey("image_extractions.id"), nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    review_runs: Mapped[list["ReviewRun"]] = relationship(back_populates="application")
    decision: Mapped["ReviewDecision | None"] = relationship(back_populates="application")


class ReviewRun(Base):
    """One review of an application: the front/back extractions merged into a
    single set of label fields, plus the per-field verdicts."""

    __tablename__ = "review_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    # field name -> "front" | "back": which image each extracted value came from.
    field_sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    # How long the user waited after pressing "Review" — near zero when the
    # images were already extracted while the form was being filled in.
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    # How long the model itself took to read the label (slowest image).
    extraction_ms: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="review_runs")
    comparisons: Mapped[list["FieldComparison"]] = relationship(back_populates="review_run")


class FieldComparison(Base):
    """One field's verdict: what the application declared vs. what the label
    actually shows, and how they were compared (exact/tolerance/enum/fuzzy)."""

    __tablename__ = "field_comparisons"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    review_run_id: Mapped[str] = mapped_column(ForeignKey("review_runs.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    application_value: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_value: Mapped[str | None] = mapped_column(String, nullable=True)
    match_type: Mapped[str] = mapped_column(String, nullable=False)  # exact/tolerance/enum/fuzzy/presence/placement
    status: Mapped[str] = mapped_column(String, nullable=False)  # match/mismatch/flagged/missing
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    review_run: Mapped[ReviewRun] = relationship(back_populates="comparisons")


class ReviewDecision(Base):
    """The agent's call on a reviewed application. The tool only pre-screens;
    this records what the human decided after looking at it."""

    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False, unique=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)  # accept/reject/follow_up
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    application: Mapped[Application] = relationship(back_populates="decision")


class ReviewBatch(Base):
    """A set of applications submitted together — e.g. an importer's 200-300
    labels. Reviewed in the background by app/batch_service.py; the agent
    doesn't need to keep the page open."""

    __tablename__ = "review_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # When the first item's images arrived — the start of review work, used
    # for the progress estimate.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["BatchItem"]] = relationship(back_populates="batch", order_by="BatchItem.row_number")


class BatchItem(Base):
    """One application within a batch: its declared fields (a row of the
    uploaded spreadsheet), its label images once uploaded, and — once
    reviewed — the resulting application record."""

    __tablename__ = "batch_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("review_batches.id"), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(nullable=False)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    declared: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Filenames as given in the spreadsheet/folder, so an interrupted upload
    # can be resumed by dropping the same folder again.
    front_image_name: Mapped[str] = mapped_column(String, nullable=False)
    back_image_name: Mapped[str | None] = mapped_column(String, nullable=True)
    front_extraction_id: Mapped[str | None] = mapped_column(ForeignKey("image_extractions.id"), nullable=True)
    back_extraction_id: Mapped[str | None] = mapped_column(ForeignKey("image_extractions.id"), nullable=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), nullable=True)
    # awaiting_images -> queued -> reviewed | error ; skipped if the batch is cancelled first
    status: Mapped[str] = mapped_column(String, nullable=False, default="awaiting_images")
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    batch: Mapped[ReviewBatch] = relationship(back_populates="items")
    application: Mapped[Application | None] = relationship()
