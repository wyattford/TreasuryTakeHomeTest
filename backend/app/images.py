"""Normalizes uploaded label photos before they reach the vision model.

Phone photos arrive rotated (orientation lives in EXIF metadata, which the
model never sees), far larger than label text needs, and in assorted formats.
Every upload is re-encoded here into one predictable shape: upright, RGB,
long edge capped at ``settings.max_image_edge_px``, JPEG.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings

NORMALIZED_CONTENT_TYPE = "image/jpeg"


class InvalidImageError(ValueError):
    """The upload isn't an image Pillow can decode."""


def normalize_label_image(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("That file isn't a readable image. Please upload a JPEG, PNG, GIF, or WebP photo.") from exc

    if image.mode in ("RGBA", "LA", "P"):
        # Flatten transparency onto white — labels are dark text on a light
        # background far more often than not, and black (the default) would
        # hide it.
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    image.thumbnail((settings.max_image_edge_px, settings.max_image_edge_px), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()
