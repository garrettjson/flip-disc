"""Text display animation for flip-disc displays."""

from typing import override

import numpy as np

from flipdisc.fonts.loader import load_font

from .base import Animation, register_animation

_VALID_MODES = {"static", "scroll_left", "scroll_up", "scroll_down"}


@register_animation("text")
class TextAnimation(Animation):
    """Displays text on the flip-disc display with static and scrolling modes."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))
        self._font = load_font("standard")
        self._text_image: np.ndarray | None = None
        self._mode: str = "static"
        self._speed: float = 7.0  # pixels per second
        self._loop: bool = True
        self._offset: float = 0.0
        self._error: str | None = None

    @override
    def configure(self, **params) -> None:
        super().configure(**params)
        if "font" in params:
            self._font = load_font(params["font"])
        if "mode" in params:
            mode = params["mode"]
            if mode not in _VALID_MODES:
                self._error = f"Invalid mode: {mode}. Must be one of {_VALID_MODES}"
                self._text_image = None
                return
            self._mode = mode
        if "speed" in params:
            self._speed = float(params["speed"])
        if "loop" in params:
            self._loop = bool(params["loop"])
        if "text" in params or "mode" in params or "font" in params:
            self._rebuild()

    def _rebuild(self) -> None:
        """Pre-render the text image based on current text and mode."""
        self._error = None
        self._text_image = None
        self._offset = 0.0
        self._completed = False

        text = self.params.get("text", "")
        if not text:
            return

        if self._mode == "scroll_left":
            self._text_image = self._font.render_line(text)
        elif self._mode == "scroll_up":
            self._text_image = self._font.render_wrapped(text, self.width)
        elif self._mode == "scroll_down":
            reversed_text = " ".join(reversed(text.split()))
            self._text_image = self._font.render_wrapped(reversed_text, self.width)
        elif self._mode == "static":
            line = self._font.render_line(text)
            if line.shape[1] > self.width or line.shape[0] > self.height:
                self._error = (
                    f"Text too large ({line.shape[1]}x{line.shape[0]}) "
                    f"for display ({self.width}x{self.height})"
                )
                self._text_image = None
            else:
                self._text_image = line

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self._text_image is None:
            return
        if self._mode == "static":
            return

        self._offset += self._speed * dt

        if self._loop:
            return

        if self._mode == "scroll_left":
            total = self.width + self._text_image.shape[1]
        elif self._mode in {"scroll_up", "scroll_down"}:
            total = self.height + self._text_image.shape[0]
        else:
            return

        if self._offset >= total:
            self._completed = True

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)

        if self._text_image is None:
            return frame

        img = self._text_image
        ih, iw = img.shape

        if self._mode == "static":
            y0 = (self.height - ih) // 2
            x0 = 0 if self.params.get("align") == "left" else (self.width - iw) // 2
            frame[y0 : y0 + ih, x0 : x0 + iw] = img
            return frame

        if self._mode == "scroll_left":
            # Text scrolls from right to left
            # offset=0 -> text starts just off the right edge
            # Vertically center the text
            y0 = (self.height - ih) // 2
            y1 = y0 + ih

            total = self.width + iw
            off = self._offset
            if self._loop and total > 0:
                off = off % total

            # src_x is position in text image, dst_x is position on display
            # Text starts at display x = (width - offset)
            start_x = int(self.width - off)

            self._blit_horizontal(frame, img, y0, y1, start_x)
            return frame

        if self._mode == "scroll_up":
            # Text scrolls from bottom to top
            total = self.height + ih
            off = self._offset
            if self._loop and total > 0:
                off = off % total

            start_y = int(self.height - off)
            self._blit_vertical(frame, img, start_y)
            return frame

        if self._mode == "scroll_down":
            # Text scrolls from top to bottom
            total = self.height + ih
            off = self._offset
            if self._loop and total > 0:
                off = off % total

            start_y = int(-ih + off)
            self._blit_vertical(frame, img, start_y)
            return frame

        return frame

    def _blit_horizontal(
        self,
        frame: np.ndarray,
        img: np.ndarray,
        y0: int,
        y1: int,
        start_x: int,
    ) -> None:
        """Blit text image onto frame at given position, clipping to bounds."""
        ih, iw = img.shape
        # Clip vertically
        fy0 = max(0, y0)
        fy1 = min(self.height, y1)
        iy0 = fy0 - y0
        iy1 = ih - (y1 - fy1)

        # Clip horizontally
        fx0 = max(0, start_x)
        fx1 = min(self.width, start_x + iw)
        ix0 = fx0 - start_x
        ix1 = iw - (start_x + iw - fx1)

        if fy0 < fy1 and fx0 < fx1:
            frame[fy0:fy1, fx0:fx1] = img[iy0:iy1, ix0:ix1]

    def _blit_vertical(self, frame: np.ndarray, img: np.ndarray, start_y: int) -> None:
        """Blit text image onto frame at given vertical position."""
        ih, iw = img.shape
        left_pad = 1
        blit_w = min(iw, self.width - left_pad)

        fy0 = max(0, start_y)
        fy1 = min(self.height, start_y + ih)
        iy0 = fy0 - start_y
        iy1 = ih - (start_y + ih - fy1)

        if fy0 < fy1 and blit_w > 0:
            frame[fy0:fy1, left_pad : left_pad + blit_w] = img[iy0:iy1, :blit_w]

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._offset = 0.0
