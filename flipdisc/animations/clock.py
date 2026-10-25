"""Clock animation — digital or analog display of current system time."""

from datetime import datetime
from typing import override

import numpy as np

from flipdisc.fonts.loader import list_fonts, load_font

from .analog_clock import AnalogClockAnimation
from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

_STYLES = ("digital", "analog")


@register_animation("clock")
class ClockAnimation(Animation):
    """Unified clock animation with digital and analog styles.

    font, format and blink_colon apply to the digital style only.
    """

    PARAMS = (
        Param("style", str, "digital", choices=_STYLES),
        Param("font", str, "standard", choices=list_fonts),
        Param("format", str, "24h", choices=("24h", "12h")),
        Param("blink_colon", bool, False),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=("binarize",))

        self._style = self.params["style"]

        # Digital state
        self._font_name = self.params["font"]
        self._font = load_font(self._font_name)
        self._format = self.params["format"]
        self._blink_colon = self.params["blink_colon"]

        # Analog delegate
        self._analog = AnalogClockAnimation(self.viewport)

    @override
    def on_configure(self, **params) -> None:
        if "style" in params:
            self._style = params["style"]
        if "font" in params:
            self._font_name = params["font"]
            self._font = load_font(self._font_name)
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

        h_img = self._font.render_line(hour_str)
        m_img = self._font.render_line(minute_str)

        fh = self._font.letter_height

        # 1px-wide colon: two dots with 3px total spacing (2 blank rows between)
        # When blink_colon is enabled, hide colon on odd seconds
        colon_visible = not (self._blink_colon and now.second % 2 == 1)
        colon = np.zeros((fh, 1), dtype=np.float32)
        if colon_visible:
            dot1 = max(0, (fh - 3) // 2)
            dot2 = min(fh - 1, dot1 + 3)
            colon[dot1, 0] = 1.0
            colon[dot2, 0] = 1.0

        # Auto-include 1px gap on each side of colon if canvas is wide enough
        hw = h_img.shape[1]
        mw = m_img.shape[1]
        if hw + 1 + mw + 2 <= self.width:  # room for gaps
            gap = np.zeros((fh, 1), dtype=np.float32)
            time_img = np.hstack([h_img, gap, colon, gap, m_img])
        else:
            time_img = np.hstack([h_img, colon, m_img])

        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        th, tw = time_img.shape
        y0 = max(0, (self.height - th) // 2)
        x0 = max(0, (self.width - tw) // 2)
        y1 = min(self.height, y0 + th)
        x1 = min(self.width, x0 + tw)
        canvas[y0:y1, x0:x1] = time_img[: y1 - y0, : x1 - x0]

        return canvas
