"""Local filesystem storage for uploaded label images. Deliberately simple —
a prototype's storage needs, not a production object-store integration."""

from __future__ import annotations

import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BACKEND_DIR / "uploads"

_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}


def save_image(content: bytes, content_type: str) -> str:
    """Writes the image under uploads/ and returns its path relative to the
    backend directory (what gets stored in the database)."""

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{uuid.uuid4()}.{_EXTENSIONS.get(content_type, 'bin')}"
    file_path.write_bytes(content)
    return str(file_path.relative_to(BACKEND_DIR))


def image_path(stored_path: str) -> Path:
    return BACKEND_DIR / stored_path
