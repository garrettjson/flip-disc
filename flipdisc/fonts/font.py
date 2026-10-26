"""Bitmap fonts: one size of a typeface, and the family of sizes text picks from.

Pixel fonts don't scale: a 5x7 letter enlarged to 10x14 is the same letter,
zoomed, not a finer one. So a typeface comes as several sizes, each drawn on
the dot grid, the way bitmap fonts were shipped in the 1980s and 90s. Text
asks a ``FontFamily`` for a height in dots and gets the drawn size nearest to
it; past the largest drawn size, that one is enlarged by a whole number, which
keeps it crisp.

Dots are placed as a typesetter would: each line has an ascent above its
baseline and a descent below; each glyph is its lit dots (its ink), placed
relative to the pen, which then moves on by the glyph's advance. The gap
between letters is part of the advance, so it's the font's choice, not the
caller's.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np

from flipdisc.gfx import draw


@dataclass(frozen=True)
class Glyph:
    """One character: its ink, where the ink sits, and how far the pen moves."""

    ink: np.ndarray  # float32 (rows, columns), just the lit dots; empty if blank
    left: int  # columns from the pen to the ink
    top: int  # rows from the top of the line to the ink
    advance: int  # columns from this character's pen position to the next

    @property
    def right(self) -> int:
        """Columns from the pen to just past the ink; 0 for a blank glyph."""
        return self.left + self.ink.shape[1] if self.ink.size else 0

    def scaled(self, k: int) -> Glyph:
        ink = np.kron(self.ink, np.ones((k, k), dtype=np.float32))
        return Glyph(ink, self.left * k, self.top * k, self.advance * k)


class BitmapFont:
    """One size of a typeface: lines ``height`` dots tall."""

    def __init__(
        self, glyphs: Mapping[str, Glyph], ascent: int, descent: int, name: str = ""
    ):
        self.name = name  # where it came from, such as "spleen/6x12"
        self.ascent = ascent  # rows above the baseline
        self.descent = descent  # rows below it, for descenders
        self.height = ascent + descent
        self._glyphs = dict(glyphs)
        typical = self._glyphs.get("H") or next(iter(self._glyphs.values()))
        blank = Glyph(np.zeros((0, 0), np.float32), 0, 0, typical.advance)
        self._glyphs.setdefault(" ", blank)
        # How far the pen moves for a typical letter, how wide the letter is,
        # and the gap between the two
        self.advance = typical.advance
        self.letter_width = typical.right
        self.spacing = max(0, self.advance - self.letter_width)
        # The rows a capital letter fills, top included and baseline excluded;
        # centring these, not the whole line, sets text visibly in the middle
        self.cap_top = typical.top if typical.ink.size else 0
        self.baseline = ascent

    def centre_top(self, rows: int) -> int:
        """The top row for a line set in the middle of ``rows`` rows, judged
        by its capitals, so descenders hang below the middle."""
        return (rows - (self.baseline - self.cap_top)) // 2 - self.cap_top

    def get_glyph(self, char: str) -> Glyph:
        """The glyph for ``char``; a blank space if the font doesn't have one."""
        return self._glyphs.get(char, self._glyphs[" "])

    def measure(self, text: str) -> int:
        """Width in dots of ``text`` on one line: from the first pen position
        to a letter's width past the last one, or the end of the last
        character's ink if that's further. So in a fixed-width font the width
        depends only on the number of characters, and a clock's digits don't
        shift as they change."""
        if not text:
            return 0
        pen = sum(self.get_glyph(ch).advance for ch in text[:-1])
        return pen + max(self.letter_width, self.get_glyph(text[-1]).right)

    def render_line(self, text: str) -> np.ndarray:
        """``text`` on one line: float32, ``height`` rows by ``measure(text)``."""
        line = np.zeros((self.height, self.measure(text)), dtype=np.float32)
        pen = 0
        for ch in text:
            glyph = self.get_glyph(ch)
            if glyph.ink.size:
                draw.image(line, glyph.ink, pen + glyph.left, glyph.top)
            pen += glyph.advance
        return line

    def render_wrapped(
        self, text: str, max_width: int, line_gap: int = 1
    ) -> np.ndarray:
        """``text`` broken into lines at most ``max_width`` dots wide,
        left-aligned and ``line_gap`` blank rows apart. A word too long for
        a line is split with hyphens.

        Returns float32, (lines * (height + line_gap) - line_gap) by
        ``max_width``.
        """
        lines: list[str] = []
        current = ""
        for word in text.split(" "):
            if self.measure(word) > max_width:
                if current:
                    lines.append(current)
                    current = ""
                lines.extend(self._hyphenate(word, max_width))
                continue
            candidate = f"{current} {word}" if current else word
            if self.measure(candidate) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)

        pitch = self.height + line_gap
        rows = max(1, len(lines)) * pitch - line_gap
        block = np.zeros((rows, max_width), dtype=np.float32)
        for i, line in enumerate(lines):
            draw.image(block, self.render_line(line), 0, i * pitch)
        return block

    def _hyphenate(self, word: str, max_width: int) -> list[str]:
        """``word`` in pieces that fit ``max_width``, each but the last ending
        in a hyphen; at least one character per piece."""
        pieces: list[str] = []
        while len(word) > 1 and self.measure(word) > max_width:
            take = 1
            while (
                take + 1 < len(word)
                and self.measure(word[: take + 1] + "-") <= max_width
            ):
                take += 1
            pieces.append(word[:take] + "-")
            word = word[take:]
        pieces.append(word)
        return pieces

    def scaled(self, k: int) -> BitmapFont:
        """This font with every dot made ``k`` by ``k``."""
        glyphs = {ch: glyph.scaled(k) for ch, glyph in self._glyphs.items()}
        return BitmapFont(
            glyphs, self.ascent * k, self.descent * k, f"{self.name} x{k}"
        )

    def __repr__(self) -> str:
        return f"BitmapFont({self.name or '?'}, {self.height} tall)"


class FontFamily:
    """The drawn sizes of one typeface."""

    def __init__(self, name: str, sizes: list[BitmapFont]):
        self.name = name
        self.sizes = sorted(sizes, key=lambda font: font.height)
        self._enlarged: dict[int, BitmapFont] = {}

    def nearest(self, height: float) -> BitmapFont:
        """The size whose line height is nearest ``height`` dots. Nearness is
        a ratio, so 9 picks 7 over 12 (9/7 < 12/9); a tie picks the smaller."""
        return self._ladder(height)[-1]

    def fit(
        self, height: float, fits: Callable[[BitmapFont], bool]
    ) -> BitmapFont | None:
        """The size nearest ``height`` if it ``fits``, or else the largest
        smaller size that does; None if none does."""
        return next(
            (font for font in reversed(self._ladder(height)) if fits(font)), None
        )

    def _ladder(self, height: float) -> list[BitmapFont]:
        """Every size up to and including the one nearest ``height``, smallest
        first. Past the largest drawn size, the ladder continues with it
        enlarged 2x, 3x, and so on."""
        height = max(height, 1.0)
        ladder = list(self.sizes)
        while ladder[-1].height < height:
            ladder.append(self._enlarge(len(ladder) - len(self.sizes) + 2))
        nearest = min(
            range(len(ladder)),
            key=lambda i: (abs(math.log(ladder[i].height / height)), ladder[i].height),
        )
        return ladder[: nearest + 1]

    def _enlarge(self, k: int) -> BitmapFont:
        if k not in self._enlarged:
            self._enlarged[k] = self.sizes[-1].scaled(k)
        return self._enlarged[k]
