"""Text display animation for flip-disc displays.

``size`` is the height of a line in dots on a 28-dot display, and grows with
the display like an object (``scale.text``): the text is set in the drawn
size of ``font`` nearest that height (see ``flipdisc/fonts/font.py``), or a
smaller one if it wouldn't fit. Scrolling speed is relative to the text, so
it reads at the same pace whatever size it's set in.
"""

from typing import override

import numpy as np

from flipdisc.fonts.font import BitmapFont
from flipdisc.fonts.loader import DEFAULT_FAMILY, list_families, load_family
from flipdisc.gfx import draw

from .base import Animation, register_animation
from .cadence import Cadence
from .params import Param
from .viewport import Viewport

_MODES = ("static", "scroll_left", "scroll_up", "scroll_down")
LINE_GAP = 1  # blank rows between wrapped lines


def _margin(font: BitmapFont) -> int:
    """Wrapped text keeps a letter's gap in from either side, so the margin
    follows the text's size like its speed does."""
    return max(1, font.spacing)


@register_animation("text")
class TextAnimation(Animation):
    """Displays text on the flip-disc display with static and scrolling modes."""

    PARAMS = (
        Param("text", str, ""),
        Param("mode", str, "static", choices=_MODES),
        Param("font", str, DEFAULT_FAMILY, choices=list_families),
        Param("size", int, 8, min=5, max=64, unit="px"),
        # At ``size``, in dots per second; it grows with the text set
        Param("speed", float, 7.0, min=0, max=1000, step=1, unit="px/s"),
        Param("loop", bool, True),
        Param("align", str, "center", choices=("center", "left")),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=("binarize",))
        self._margin = 1  # wrapped text's inset from either side, per font
        self._font: BitmapFont | None = None
        self._text_image: np.ndarray | None = None
        self._speed_scale = 1.0  # set text's dots per dot at ``size``
        self._offset: int = 0  # whole pixels scrolled
        self._scroll = Cadence()
        self._error: str | None = None

    @override
    def on_configure(self, **params) -> None:
        if params.keys() & {"text", "mode", "font", "size"}:
            self._rebuild()

    def _rebuild(self) -> None:
        """Set the text in a font that fits, for the current text and mode."""
        self._error = None
        self._font = None
        self._text_image = None
        self._offset = 0
        self._scroll.reset()
        self._completed = False

        text, mode = self.params["text"], self.params["mode"]
        if not text:
            return

        family = load_family(self.params["font"])
        size = self.params["size"]

        def fits(font: BitmapFont) -> bool:
            if font.height > self.height:
                return False
            if mode == "static":
                return font.measure(text) <= self.width
            if mode == "scroll_left":
                return True
            return font.letter_width <= self.width - 2 * _margin(font)

        font = family.fit(self.scale.text(size), fits)
        if font is None:
            smallest = family.sizes[0]
            self._error = (
                f"Text too large ({smallest.measure(text)}x{smallest.height} "
                f"at the smallest size) for display ({self.width}x{self.height})"
            )
            return

        # Pace in letters (or lines) per second, as at the design size
        design = family.nearest(size)
        if mode == "scroll_left":
            self._speed_scale = font.advance / design.advance
        else:
            self._speed_scale = (font.height + LINE_GAP) / (design.height + LINE_GAP)

        self._font = font
        self._margin = _margin(font)
        wrap_width = self.width - 2 * self._margin
        if mode in {"static", "scroll_left"}:
            self._text_image = font.render_line(text)
        elif mode == "scroll_up":
            self._text_image = font.render_wrapped(text, wrap_width, LINE_GAP)
        else:
            reversed_text = " ".join(reversed(text.split()))
            self._text_image = font.render_wrapped(reversed_text, wrap_width, LINE_GAP)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self._text_image is None or self.params["mode"] == "static":
            return

        speed = self.params["speed"] * self._speed_scale
        self._offset += self._scroll.advance(speed, dt)

        if self.params["loop"] or self._offset < self._travel():
            return
        self._completed = True

    def _travel(self) -> int:
        """How far the text scrolls from entering the display to leaving it."""
        ih, iw = self._text_image.shape
        if self.params["mode"] == "scroll_left":
            return self.width + iw
        return self.height + ih

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        if self._text_image is None:
            return frame

        img = self._text_image
        ih, iw = img.shape
        mode = self.params["mode"]

        if mode == "static":
            left = 0 if self.params["align"] == "left" else (self.width - iw) // 2
            draw.image(frame, img, left, self._font.centre_top(self.height))
            return frame

        travel = self._travel()
        offset = self._offset % travel if self.params["loop"] else self._offset
        if mode == "scroll_left":
            # Enters at the right edge and moves left
            top = self._font.centre_top(self.height)
            draw.image(frame, img, self.width - offset, top)
        elif mode == "scroll_up":
            draw.image(frame, img, self._margin, self.height - offset)
        else:
            draw.image(frame, img, self._margin, offset - ih)
        return frame

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._offset = 0
        self._scroll.reset()
