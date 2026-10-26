"""Draw the reference images of the fonts, checked in to ``assets/text/``.

- ``font_sizes.png``: every drawn size of every family, at the same dot size.
- ``font_specimen.png``: the clock and a page of text on displays 28, 56 and
  126 dots square, in each family, as the animations set them.

Regenerate them after changing a font or how text is set:

    uv run python -m flipdisc.tools.font_images

Everything is drawn here with NumPy, labels included (in Spleen 8x16), and
the clock is stopped at 12:34, so the same code makes the same pixels on any
machine. ``test_font_images.py`` fails when the checked-in images are stale.
"""

import argparse
from datetime import datetime
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from flipdisc.animations import Viewport, get_animation
from flipdisc.animations.text import LINE_GAP
from flipdisc.fonts.font import BitmapFont
from flipdisc.fonts.loader import list_families, load_family
from flipdisc.gfx.postprocessing import apply_processing_pipeline

OUT_DIR = Path("assets/text")

# Colours of the real panels: a black face, dark discs, white discs. Labels
# are white too. Pixels are indices into this palette
_PALETTE = (0, 0, 0, 40, 40, 40, 255, 255, 255)
_FACE, _UNLIT, _LIT = 0, 1, 2
_DISC = 0.42  # a disc's radius, in dots

SAMPLE_LINE = "Hello 12:34 Ag?!"
SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. It is 72F and sunny, "
    "wind 5 mph. Next train in 12 min. 0123456789 ?!&%"
)
DISPLAYS = (28, 56, 126)
PANEL = 504  # pixels across every display in the specimen: 18, 9, 4 per dot
_TIME = datetime(2026, 10, 25, 12, 34)
_MARGIN = 24  # pixels around the sheet
_GAP = 16  # pixels between a label and what it labels, and between rows


def discs(frame: np.ndarray, pitch: int) -> np.ndarray:
    """A 1-bit frame as the panel shows it: a disc every ``pitch`` pixels."""
    offsets = np.arange(pitch) + 0.5 - pitch / 2
    disc = offsets[:, None] ** 2 + offsets[None, :] ** 2 <= (_DISC * pitch) ** 2
    colours = np.where(frame, _LIT, _UNLIT)
    cells = np.where(disc[None, :, None, :], colours[:, None, :, None], _FACE)
    rows, columns = frame.shape
    return cells.reshape(rows * pitch, columns * pitch).astype(np.uint8)


def _label_font() -> BitmapFont:
    return load_family("spleen").nearest(16)


def label(text: str) -> np.ndarray:
    pixels = _label_font().render_line(text) > 0.5
    return np.where(pixels, _LIT, _FACE).astype(np.uint8)


def _sheet(items: list[tuple[np.ndarray, int, int]]) -> np.ndarray:
    """A sheet just big enough for ``items`` (image, left, top), with a
    margin to the right and below."""
    width = max(left + image.shape[1] for image, left, _ in items) + _MARGIN
    height = max(top + image.shape[0] for image, _, top in items) + _MARGIN
    sheet = np.full((height, width), _FACE, dtype=np.uint8)
    for image, left, top in items:
        sheet[top : top + image.shape[0], left : left + image.shape[1]] = image
    return sheet


def font_sizes() -> np.ndarray:
    """Every drawn size of every family, at the same dot size."""
    pitch = 4
    fonts = [font for name in list_families() for font in load_family(name).sizes]
    indent = _MARGIN + max(label(font.name).shape[1] for font in fonts) + _GAP
    items = []
    top = _MARGIN
    for i, font in enumerate(fonts):
        if i and font.name.split("/")[0] != fonts[i - 1].name.split("/")[0]:
            top += 2 * _GAP  # a wider gap between families
        sample = discs(font.render_line(SAMPLE_LINE) > 0.5, pitch)
        name = label(font.name)
        items.append((name, _MARGIN, top + (sample.shape[0] - name.shape[0]) // 2))
        items.append((sample, indent, top))
        top += max(sample.shape[0], name.shape[0]) + _GAP
    return _sheet(items)


def clock(size: int, family: str) -> tuple[np.ndarray, BitmapFont | None]:
    """The digital clock at 12:34 on a ``size`` display, and its font."""
    anim = get_animation("clock", Viewport(size, size))
    anim.configure(font=family)
    with mock.patch("flipdisc.animations.clock.datetime") as clock_time:
        clock_time.now.return_value = _TIME
        frame = apply_processing_pipeline(anim.render_gray(), anim.processing_steps)
    return frame, anim._font()


def page(size: int, family: str) -> tuple[np.ndarray, BitmapFont | None]:
    """A page of wrapped text on a ``size`` display, and its font: the
    scrolling text when its first line is a margin from the top, cut after
    the last line that fits whole."""
    anim = get_animation("text", Viewport(size, size))
    anim.configure(text=SAMPLE_TEXT, mode="scroll_up", font=family)
    font, margin = anim._font, anim._margin
    if font is None:
        return np.zeros((size, size), dtype=bool), None
    anim._offset = size - margin
    frame = apply_processing_pipeline(anim.render_gray(), anim.processing_steps)
    pitch = font.height + LINE_GAP
    lines = max(1, (size - 2 * margin + LINE_GAP) // pitch)
    frame[margin + lines * pitch - LINE_GAP :] = False
    return frame, font


def font_specimen() -> np.ndarray:
    """The clock and a page of text in each family, on each display size."""
    columns = [(family, kind) for family in list_families() for kind in (clock, page)]
    note = label(
        "Every display is drawn the same width here; "
        "on the wall a 56 x 56 is twice as wide as a 28 x 28."
    )
    rows = _label_font().height
    items = [(note, _MARGIN, _MARGIN)]
    top = _MARGIN + rows + 2 * _GAP
    for c, (family, kind) in enumerate(columns):
        heading = label(f"{family}: {'clock' if kind is clock else 'text'}")
        items.append((heading, _MARGIN + c * (PANEL + 2 * _GAP), top))
    top += rows + 2 * _GAP
    for size in DISPLAYS:
        for c, (family, kind) in enumerate(columns):
            left = _MARGIN + c * (PANEL + 2 * _GAP)
            frame, font = kind(size, family)
            picked = font.name if font else "nothing fits"
            caption = label(f"{size} x {size}  size 8 -> {picked}")
            items.append((caption, left, top))
            panel = discs(frame, PANEL // size)
            items.append((panel, left, top + rows + _GAP // 2))
        top += rows + _GAP // 2 + PANEL + 2 * _GAP
    return _sheet(items)


IMAGES = {"font_sizes.png": font_sizes, "font_specimen.png": font_specimen}


def save(pixels: np.ndarray, path: Path) -> None:
    """``pixels`` (palette indices) as a palette PNG."""
    image = Image.fromarray(pixels)
    image.putpalette(_PALETTE)
    image.save(path, optimize=True)


def write_images(out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, make in IMAGES.items():
        save(make(), out_dir / name)
        paths.append(out_dir / name)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output folder")
    for path in write_images(parser.parse_args().out):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
