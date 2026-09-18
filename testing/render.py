"""Renders a `LabelContent` into front/back label images with Pillow.

This is not trying to be a graphic designer — it's producing a plausible,
readable label layout (brand name up front, name/address + Government
Warning on the back, the way real bottles are laid out) so the vision model
has realistic text to transcribe. Visual polish stops the moment legibility
is achieved; `distortions.py` is what actually stresses the model.
"""

from __future__ import annotations

from pathlib import Path

from label_content import LabelContent
from PIL import Image, ImageDraw, ImageFont

FRONT_SIZE = (1000, 1300)
BACK_SIZE = (1000, 1300)
BACKGROUND = (245, 240, 228)
INK = (25, 22, 20)
RULE = (150, 130, 90)

_CLASS_ACCENT = {
    "distilled_spirits": (120, 40, 30),
    "wine": (85, 20, 40),
    "malt_beverage": (150, 100, 20),
}

_FONT_DIRS = [
    Path("/System/Library/Fonts/Supplemental"),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
]

_FONT_CANDIDATES = {
    "regular": ["Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "bold": ["Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "italic": ["Arial Italic.ttf", "DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"],
}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    key = (style, size)
    if key not in _font_cache:
        for directory in _FONT_DIRS:
            for name in _FONT_CANDIDATES[style]:
                path = directory / name
                if path.exists():
                    _font_cache[key] = ImageFont.truetype(str(path), size)
                    break
            if key in _font_cache:
                break
        else:
            _font_cache[key] = ImageFont.load_default(size=size)
    return _font_cache[key]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    top: int,
    canvas_width: int,
    line_gap: int,
    fill=INK,
) -> int:
    y = top
    for line in lines:
        width = draw.textlength(line, font=font)
        draw.text(((canvas_width - width) / 2, y), line, font=font, fill=fill)
        bbox = font.getbbox(line)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def _draw_wrapped_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    top: int,
    canvas_width: int,
    max_text_width: int,
    line_gap: int,
    fill=INK,
) -> int:
    """Wraps and centers `text` starting at `top`, returning the y position
    just below it. Combines `_wrap` + `_draw_centered_lines` so callers pass
    each font once instead of once per step."""

    return _draw_centered_lines(draw, _wrap(draw, text, font, max_text_width), font, top, canvas_width, line_gap, fill=fill)


def _draw_wrapped_left(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    left: int,
    top: int,
    max_text_width: int,
    line_gap: int,
    fill=INK,
) -> int:
    """Left-aligned counterpart to `_draw_wrapped_centered`, used for the
    back label's address/origin/sulfite/warning blocks."""

    y = top
    for line in _wrap(draw, text, font, max_text_width):
        draw.text((left, y), line, font=font, fill=fill)
        bbox = font.getbbox(line)
        y += (bbox[3] - bbox[1]) + line_gap
    return y


def render_front(label: LabelContent) -> Image.Image:
    image = Image.new("RGB", FRONT_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    width, _height = FRONT_SIZE
    accent = _CLASS_ACCENT.get(label.beverage_class, (100, 100, 100))

    draw.rectangle([30, 30, width - 30, FRONT_SIZE[1] - 30], outline=accent, width=6)
    draw.rectangle([50, 50, width - 50, FRONT_SIZE[1] - 50], outline=RULE, width=2)

    max_text_width = width - 220
    y = 180
    y = _draw_wrapped_centered(draw, label.brand_name, _font("bold", 60), y, width, max_text_width, 14, fill=accent)
    y += 30

    if label.fanciful_name:
        y = _draw_wrapped_centered(draw, label.fanciful_name, _font("italic", 36), y, width, max_text_width, 10)
        y += 20

    y = _draw_wrapped_centered(draw, label.class_type, _font("regular", 42), y, width, max_text_width, 12)
    y += 20

    if label.appellation:
        y = _draw_wrapped_centered(draw, label.appellation, _font("regular", 28), y, width, max_text_width, 8)
        y += 20

    draw.line([120, y + 10, width - 120, y + 10], fill=RULE, width=2)

    footer_font = _font("bold", 34)
    footer_parts = []
    if label.abv_percent is not None:
        footer_parts.append(f"{label.abv_percent:g}% Alc./Vol.")
    footer_parts.append(label.net_contents)
    footer_line = "        ".join(footer_parts)
    footer_y = FRONT_SIZE[1] - 160
    footer_width = draw.textlength(footer_line, font=footer_font)
    draw.text(((width - footer_width) / 2, footer_y), footer_line, font=footer_font, fill=INK)

    return image


def render_back(label: LabelContent) -> Image.Image:
    image = Image.new("RGB", BACK_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    width, _height = BACK_SIZE
    margin = 110
    max_text_width = width - 2 * margin

    draw.rectangle([30, 30, width - 30, BACK_SIZE[1] - 30], outline=RULE, width=4)

    y = 90
    y = _draw_wrapped_left(draw, label.name_address, _font("regular", 30), margin, y, max_text_width, 12)
    y += 30

    if label.country_of_origin:
        y = _draw_wrapped_left(draw, label.country_of_origin, _font("regular", 30), margin, y, max_text_width, 10)
        y += 20

    if label.sulfite_declaration:
        y = _draw_wrapped_left(draw, label.sulfite_declaration, _font("regular", 28), margin, y, max_text_width, 10)
        y += 20

    for disclosure in label.other_disclosures:
        y = _draw_wrapped_left(draw, f"• {disclosure}", _font("regular", 26), margin, y, max_text_width, 8)
        y += 10

    if label.government_warning_text:
        y += 40
        draw.rectangle([margin - 20, y - 20, width - margin + 20, BACK_SIZE[1] - 80], outline=INK, width=3)
        _draw_wrapped_left(draw, label.government_warning_text, _font("regular", 26), margin, y, max_text_width - 20, 8)

    return image
