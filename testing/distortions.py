"""Pillow-only image distortions simulating how a real label photo can
degrade: camera blur, a crooked shot, bad lighting, sensor grain, heavy
recompression, and glare off glass or a glossy label. Each function takes and
returns a PIL RGB Image so they can be composed freely.
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

_BACKGROUND = (245, 240, 228)  # matches render.py's label background


def blur(image: Image.Image, radius: float = 3.2) -> Image.Image:
    return image.filter(ImageFilter.GaussianBlur(radius=radius))


def rotate(image: Image.Image, degrees: float = 7.0) -> Image.Image:
    """Rotates as if the photo were taken at an angle, expanding the canvas
    and filling the new corners with the label's own background color rather
    than black, since a real photo would show whatever surface is behind it."""

    return image.rotate(degrees, expand=True, fillcolor=_BACKGROUND, resample=Image.BICUBIC)


def low_contrast(image: Image.Image, contrast_factor: float = 0.35, brightness_factor: float = 1.25) -> Image.Image:
    washed_out = ImageEnhance.Brightness(image).enhance(brightness_factor)
    return ImageEnhance.Contrast(washed_out).enhance(contrast_factor)


def noise(image: Image.Image, sigma: float = 28.0, opacity: float = 0.35) -> Image.Image:
    """Blends in Pillow's built-in monochromatic noise generator to simulate
    sensor grain from a low-light phone photo."""

    grain = Image.effect_noise(image.size, sigma).convert("RGB")
    return Image.blend(image, grain, opacity)


def jpeg_artifacts(image: Image.Image, quality: int = 8) -> Image.Image:
    """Round-trips through a heavily-compressed JPEG to introduce blocking
    and color-banding artifacts, as if the label were re-photographed and
    re-compressed several times before reaching the reviewer."""

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def glare(image: Image.Image, seed: int = 0) -> Image.Image:
    """Overlays a soft, bright ellipse across part of the label, as if light
    were reflecting off glass or a glossy label surface and washing out
    whatever text sits underneath it."""

    rng = random.Random(seed)
    width, height = image.size
    overlay = Image.new("L", image.size, 0)
    glare_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))

    cx, cy = rng.randint(int(width * 0.2), int(width * 0.8)), rng.randint(int(height * 0.15), int(height * 0.55))
    rx, ry = int(width * 0.35), int(height * 0.22)

    draw = ImageDraw.Draw(overlay)
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=200)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=min(rx, ry) / 2))

    white = Image.new("RGBA", image.size, (255, 255, 255, 255))
    glare_layer = Image.composite(white, glare_layer, overlay)

    return Image.alpha_composite(image.convert("RGBA"), glare_layer).convert("RGB")


def blur_rotate(image: Image.Image) -> Image.Image:
    return blur(rotate(image, degrees=5.0), radius=1.8)


DISTORTIONS = {
    "clean": lambda image: image,
    "blur": blur,
    "rotate": rotate,
    "low_contrast": low_contrast,
    "noise": noise,
    "jpeg": jpeg_artifacts,
    "glare": glare,
    "blur_rotate": blur_rotate,
}


def apply_distortion(image: Image.Image, name: str) -> Image.Image:
    if name not in DISTORTIONS:
        raise ValueError(f"Unknown distortion {name!r}. Known: {sorted(DISTORTIONS)}")
    return DISTORTIONS[name](image)
