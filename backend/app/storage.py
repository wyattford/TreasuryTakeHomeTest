"""Local filesystem storage for uploaded label images. Deliberately simple —
a prototype's storage needs, not a production object-store integration."""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import LabelImage

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"


def save_image(content: bytes, content_type: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}.get(content_type, "bin")
    file_path = UPLOAD_DIR / f"{uuid.uuid4()}.{extension}"
    file_path.write_bytes(content)
    return str(file_path.relative_to(UPLOAD_DIR.parent))


def save_label_image_record(db: Session, application_id: str, side: str, content: bytes, content_type: str) -> None:
    """Saves the image to disk and records it against the application. Shared
    by the single-review and batch item endpoints."""

    file_path = save_image(content, content_type)
    db.add(LabelImage(application_id=application_id, side=side, file_path=file_path, content_type=content_type))
