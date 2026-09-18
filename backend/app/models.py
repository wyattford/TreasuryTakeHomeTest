import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Application(Base):
    """Fields an applicant declares on TTB F 5100.31 (the COLA application) —
    what the label is checked *against*, not what's read off the image."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    beverage_class: Mapped[str] = mapped_column(String, nullable=False)
    imported: Mapped[bool] = mapped_column(default=False)

    brand_name: Mapped[str] = mapped_column(String, nullable=False)
    fanciful_name: Mapped[str | None] = mapped_column(String, nullable=True)
    class_type: Mapped[str] = mapped_column(String, nullable=False)
    abv: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_contents: Mapped[str] = mapped_column(String, nullable=False)
    name_address: Mapped[str] = mapped_column(String, nullable=False)
    country_of_origin: Mapped[str | None] = mapped_column(String, nullable=True)
    appellation: Mapped[str | None] = mapped_column(String, nullable=True)
    sulfite_declaration: Mapped[str | None] = mapped_column(String, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    label_images: Mapped[list["LabelImage"]] = relationship(back_populates="application")
    extraction_results: Mapped[list["ExtractionResult"]] = relationship(back_populates="application")


class LabelImage(Base):
    __tablename__ = "label_images"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # "front" | "back"
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="label_images")


class ExtractionResult(Base):
    """One VLM extraction run over an application's label image(s)."""

    __tablename__ = "extraction_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    extracted_fields: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    application: Mapped[Application] = relationship(back_populates="extraction_results")
    comparisons: Mapped[list["FieldComparison"]] = relationship(back_populates="extraction_result")


class FieldComparison(Base):
    """One field's verdict: what the application declared vs. what the label
    actually shows, and how they were compared (exact/tolerance/enum/fuzzy)."""

    __tablename__ = "field_comparisons"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    extraction_result_id: Mapped[str] = mapped_column(ForeignKey("extraction_results.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    application_value: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_value: Mapped[str | None] = mapped_column(String, nullable=True)
    match_type: Mapped[str] = mapped_column(String, nullable=False)  # exact/tolerance/enum/fuzzy/presence
    status: Mapped[str] = mapped_column(String, nullable=False)  # match/mismatch/flagged/missing
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    extraction_result: Mapped[ExtractionResult] = relationship(back_populates="comparisons")


class ReviewBatch(Base):
    __tablename__ = "review_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list["BatchItem"]] = relationship(back_populates="batch")


class BatchItem(Base):
    __tablename__ = "batch_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("review_batches.id"), nullable=False)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/done/error
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    batch: Mapped[ReviewBatch] = relationship(back_populates="items")
