"""Clock animation — digital or analog display of current system time.

The digital face is set like text (``text.py``): ``size`` is its height on a
28-dot display, in the drawn size of ``font`` nearest it that fits.
"""

from datetime import datetime
from typing import override

import numpy as np

from flipdisc.fonts.font import BitmapFont
from flipdisc.fonts.loader import DEFAULT_FAMILY, list_families, load_family
from flipdisc.gfx import draw

from .analog_clock import AnalogClockAnimation
from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

_STYLES = ("digital", "analog")


@register_animation("clock")
class ClockAnimation(Animation):
    """Unified clock animation with digital and analog styles.

    font, size, format and blink_colon apply to the digital style only.
    """

    PARAMS = (
        Param("style", str, "digital", choices=_STYLES),
        Param("font", str, DEFAULT_FAMILY, choices=list_families),
        Param("size", int, 8, min=5, max=64, unit="px"),
        Param("format", str, "24h", choices=("24h", "12h")),
        Param("blink_colon", bool, False),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=("binarize",))

        self._style = self.params["style"]

        # Digital state
        self._format = self.params["format"]
        self._blink_colon = self.params["blink_colon"]

        # Analog delegate
        self._analog = AnalogClockAnimation(self.viewport)

    @override
    def on_configure(self, **params) -> None:
        if "style" in params:
            self._style = params["style"]
        if "format" in params:
            self._format = params["format"]
        if "blink_colon" in params:
            self._blink_colon = params["blink_colon"]

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._analog.step(dt)

    @override
    def render_gray(self) -> np.ndarray:
        if self._style == "analog":
            return self._analog.render_gray()
        return self._render_digital()

    def _render_digital(self) -> np.ndarray:
        now = datetime.now()

        if self._format == "12h":
            hour_str = (now.strftime("%I").lstrip("0") or "12").zfill(2)
        else:
            hour_str = now.strftime("%H")
        minute_str = now.strftime("%M")

        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        family = load_family(self.params["font"])
        target = self.scale.text(self.params["size"])
        font = family.fit(target, lambda f: self._fits(f, gap=0))
        if font is None:
            return canvas

        # The colon is just its ink, with a gap either side if there's room:
        # a whole character cell would push the digits apart. A font sets its
        # colon for text, low beside lowercase letters; between digits it
        # belongs in the middle of their height, as fonts' raised time colons
        # are
        colon = font.get_glyph(":").ink
        digit_rows = font.baseline - font.cap_top
        colon_top = font.cap_top + (digit_rows - colon.shape[0]) // 2
        gap = self._colon_gap(font)
        gap = gap if self._fits(font, gap) else 0
        digits = font.measure("00")
        left = (self.width - self._width(font, gap)) // 2
        top = font.centre_top(self.height)

        draw.image(canvas, font.render_line(hour_str), left, top)
        left += digits + gap
        # When blink_colon is enabled, hide colon on odd seconds
        if not (self._blink_colon and now.second % 2 == 1):
            draw.image(canvas, colon, left, top + colon_top)
        left += colon.shape[1] + gap
        draw.image(canvas, font.render_line(minute_str), left, top)
        return canvas

    @staticmethod
    def _colon_gap(font: BitmapFont) -> int:
        """Space either side of the colon: a letter's spacing, and half the
        colon's width again, so a wide colon (X11's) isn't crowded."""
        return font.spacing + font.get_glyph(":").ink.shape[1] // 2

    @staticmethod
    def _width(font: BitmapFont, gap: int) -> int:
        """Width of HH:MM in ``font`` with ``gap`` dots either side of the colon."""
        return 2 * font.measure("00") + font.get_glyph(":").ink.shape[1] + 2 * gap

    def _fits(self, font: BitmapFont, gap: int) -> bool:
        return font.height <= self.height and self._width(font, gap) <= self.width
