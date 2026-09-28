import io

import pytest
from PIL import Image

from app.config import settings
from app.images import InvalidImageError, normalize_label_image


def _encode(image: Image.Image, fmt: str, **kwargs) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def test_exif_rotation_is_applied():
    # A phone photo stored sideways with an EXIF "rotate 90" tag (6) must
    # reach the model upright.
    exif = Image.Exif()
    exif[0x0112] = 6
    raw = _encode(Image.new("RGB", (400, 200), "white"), "JPEG", exif=exif)
    with Image.open(io.BytesIO(normalize_label_image(raw))) as result:
        assert result.size == (200, 400)


def test_large_images_are_downscaled():
    raw = _encode(Image.new("RGB", (4000, 3000), "white"), "PNG")
    with Image.open(io.BytesIO(normalize_label_image(raw))) as result:
        assert max(result.size) == settings.max_image_edge_px
        assert result.format == "JPEG"


def test_transparent_png_is_flattened_to_rgb():
    raw = _encode(Image.new("RGBA", (100, 100), (0, 0, 0, 0)), "PNG")
    with Image.open(io.BytesIO(normalize_label_image(raw))) as result:
        assert result.mode == "RGB"
        assert result.getpixel((50, 50)) == (255, 255, 255)


def test_image_with_too_many_pixels_is_refused_before_decoding():
    # 64 MP, but a 1-bit solid image compresses to a few KB.
    out = io.BytesIO()
    Image.new("1", (8000, 8000)).save(out, format="PNG")
    assert len(out.getvalue()) < 100_000
    with pytest.raises(InvalidImageError, match="too large"):
        normalize_label_image(out.getvalue())


def test_non_image_is_rejected():
    with pytest.raises(InvalidImageError):
        normalize_label_image(b"%PDF-1.7 not an image")
