"""Reading BDF, the plain-text bitmap font format of X11.

A BDF file is one font at one pixel size: its ascent and descent, and for
each character a bitmap, where the bitmap sits relative to the pen, and how
far the pen moves on. Only what drawing text needs is read, and only the
printable ASCII characters. The format is Adobe's Glyph Bitmap Distribution
Format, version 2.1.
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np

from flipdisc.exceptions import FontError

from .font import BitmapFont, Glyph

# The printable ASCII characters, space to tilde
PRINTABLE = range(32, 127)


def read_bdf(path: str | Path) -> BitmapFont:
    """The font in the BDF file at ``path``."""
    ascent = descent = None
    glyphs: dict[str, Glyph] = {}
    lines = iter(Path(path).read_text(encoding="latin-1").splitlines())
    for line in lines:
        key, _, value = line.partition(" ")
        if key == "FONT_ASCENT":
            ascent = int(value)
        elif key == "FONT_DESCENT":
            descent = int(value)
        elif key == "STARTCHAR":
            if ascent is None or descent is None:
                raise FontError(f"{path}: FONT_ASCENT and FONT_DESCENT must come first")
            code, glyph = _read_char(lines, ascent, path)
            if code in PRINTABLE:
                glyphs[chr(code)] = glyph
    if not glyphs:
        raise FontError(f"{path}: no printable characters")
    path = Path(path)
    return BitmapFont(glyphs, ascent, descent, f"{path.parent.name}/{path.stem}")


def _read_char(lines: Iterator[str], ascent: int, path) -> tuple[int, Glyph]:
    """The character code and glyph from STARTCHAR up to ENDCHAR."""
    code = advance = None
    width = height = x = y = 0
    bits = np.zeros((0, 0), dtype=bool)
    for line in lines:
        key, _, value = line.partition(" ")
        if key == "ENCODING":
            code = int(value.split()[0])
        elif key == "DWIDTH":
            advance = int(value.split()[0])
        elif key == "BBX":
            width, height, x, y = map(int, value.split())
        elif key == "BITMAP":
            # Each row is hex, left-aligned and padded to whole bytes
            rows = [bytes.fromhex(next(lines)) for _ in range(height)]
            bits = np.unpackbits(np.frombuffer(b"".join(rows), np.uint8))
            bits = bits.reshape(height, -1)[:, :width].astype(bool)
        elif key == "ENDCHAR":
            break
    if code is None or advance is None:
        raise FontError(f"{path}: a character without ENCODING or DWIDTH")

    # Keep only the lit dots, so every glyph's box is its ink whatever the
    # file says (some fonts box every character as the whole cell)
    rows = np.flatnonzero(bits.any(axis=1))
    cols = np.flatnonzero(bits.any(axis=0))
    if rows.size == 0:
        return code, Glyph(np.zeros((0, 0), np.float32), 0, 0, advance)
    ink = bits[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1].astype(np.float32)
    # BBX's y is the bottom of the box above the baseline, which is ``ascent``
    # rows down from the top of the line
    top = ascent - (y + height) + int(rows[0])
    return code, Glyph(ink, x + int(cols[0]), top, advance)
