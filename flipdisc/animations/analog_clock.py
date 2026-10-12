"""Analog clock animation with round face, hour markers, and two hands."""

import math
from datetime import datetime
from typing import override

import numpy as np

from .supersampled import SupersampledAnimation


def _draw_line(frame: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> None:
    """Draw a 1px line using Bresenham's algorithm."""
    h, w = frame.shape
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    steps = int(max(dx, dy))
    if steps == 0:
        return

    xs = (x1 - x0) / steps
    ys = (y1 - y0) / steps

    i = np.arange(steps + 1)
    px = np.round(x0 + i * xs).astype(int)
    py = np.round(y0 + i * ys).astype(int)
    valid = (px >= 0) & (px < w) & (py >= 0) & (py < h)
    frame[py[valid], px[valid]] = 1.0


class AnalogClockAnimation(SupersampledAnimation):
    """Analog clock showing current system time with hour/minute hands."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, supersample=4, processing_steps=("binarize",))

        # Hi-res geometry for circle and minor dots
        self.cx = (self.hwidth - 1) / 2
        self.cy = (self.hheight - 1) / 2
        dim = min(self.hwidth, self.hheight)
        self.radius = 0.45 * dim
        self._minor_dot_r = 0.84 * self.radius

        # Output-space geometry for major markers and hands (1px at native res)
        self._out_cx = (width - 1) / 2
        self._out_cy = (height - 1) / 2
        out_dim = min(width, height)
        out_radius = 0.45 * out_dim
        self._out_major_outer = 0.92 * out_radius
        self._out_major_inner = 0.80 * out_radius
        self._out_minute = 0.80 * out_radius
        self._out_hour = 0.56 * out_radius

        # Pre-compute the static clock face (circle + minor dots only)
        self._face = self._build_face()

    def _build_face(self) -> np.ndarray:
        """Render circle outline and minor hour dots to a cached array."""
        face = np.zeros((self.hheight, self.hwidth), dtype=np.float32)

        # Draw circle outline via distance-from-center threshold
        half_thick = 0.5 * self.supersample
        yy, xx = np.mgrid[0 : self.hheight, 0 : self.hwidth]
        dist = np.sqrt((xx - self.cx) ** 2 + (yy - self.cy) ** 2)
        circle_mask = (dist >= self.radius - half_thick) & (
            dist <= self.radius + half_thick
        )
        face[circle_mask] = 1.0

        # Minor hour dots — grid-snapped squares for clean 1-output-pixel dots
        s = self.supersample
        for h in range(12):
            if h % 3 == 0:
                continue
            angle = 2 * math.pi * h / 12
            sin_a = math.sin(angle)
            cos_a = math.cos(angle)
            dot_cx = round(self.cx + self._minor_dot_r * sin_a)
            dot_cy = round(self.cy - self._minor_dot_r * cos_a)
            gx = (dot_cx // s) * s
            gy = (dot_cy // s) * s
            face[gy : gy + s, gx : gx + s] = 1.0

        return face

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt

    @override
    def render_hires(self) -> np.ndarray:
        return self._face.copy()

    @override
    def render_gray(self) -> np.ndarray:
        # Downsample the hi-res face (circle + minor dots)
        frame = super().render_gray()

        # Draw major markers at output resolution (1px lines)
        for h in range(0, 12, 3):
            angle = 2 * math.pi * h / 12
            sin_a = math.sin(angle)
            cos_a = math.cos(angle)
            _draw_line(
                frame,
                self._out_cx + self._out_major_outer * sin_a,
                self._out_cy - self._out_major_outer * cos_a,
                self._out_cx + self._out_major_inner * sin_a,
                self._out_cy - self._out_major_inner * cos_a,
            )

        # Draw hands at output resolution (1px lines)
        now = datetime.now()
        h = now.hour % 12
        m = now.minute

        hour_angle = 2 * math.pi * (h + m / 60) / 12
        _draw_line(
            frame,
            self._out_cx,
            self._out_cy,
            self._out_cx + self._out_hour * math.sin(hour_angle),
            self._out_cy - self._out_hour * math.cos(hour_angle),
        )

        minute_angle = 2 * math.pi * m / 60
        _draw_line(
            frame,
            self._out_cx,
            self._out_cy,
            self._out_cx + self._out_minute * math.sin(minute_angle),
            self._out_cy - self._out_minute * math.cos(minute_angle),
        )

        return frame
