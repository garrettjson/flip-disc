"""Analog clock animation with round face, hour markers, and two hands.

Positions are fractions of the display. The face, the quarter-hour markers,
and the hands are lines, one dot wide on a 28-dot display and a little wider
on bigger ones; the other hour markers are dots that grow with the display
(see ``scaling.py``).
"""

import math
from datetime import datetime
from typing import override

import numpy as np

from flipdisc.gfx import draw

from .base import Animation
from .viewport import Viewport

# As fractions of the face's radius
_RADIUS = 0.45  # of the display's smaller dimension
_MAJOR_OUTER = 0.92
_MAJOR_INNER = 0.80
_MINOR_DOT = 0.84
_MINUTE_HAND = 0.80
_HOUR_HAND = 0.56


def _direction(turns: float) -> np.ndarray:
    """Unit (x, y) pointing ``turns`` of the way round clockwise from 12."""
    angle = 2 * math.pi * turns
    return np.array([math.sin(angle), -math.cos(angle)])


class AnalogClockAnimation(Animation):
    """Analog clock showing current system time with hour/minute hands."""

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)

        self._line = self.scale.line()
        # On a dot's centre, so lines through it don't straddle two columns
        self._centre = np.array([(self.width - 1) // 2, (self.height - 1) // 2]) + 0.5
        # Half a dot in, so the outline clears the edge on the short side
        self._radius = _RADIUS * self.scale.short_side - 0.5

        # The face never changes, so it's drawn once
        self._face = np.zeros((self.height, self.width), dtype=np.float32)
        draw.ring(self._face, self._centre, self._radius, self._line)
        for hour in range(12):
            if hour % 3 == 0:
                outer = self._point(hour / 12, _MAJOR_OUTER)
                inner = self._point(hour / 12, _MAJOR_INNER)
                draw.line(self._face, outer, inner, self._line)
            else:
                dot = self._point(hour / 12, _MINOR_DOT)
                draw.block(self._face, dot, self.scale.dots(1))

    def _point(self, turns: float, reach: float) -> np.ndarray:
        """The point ``reach`` of the radius out from the centre, ``turns`` of
        the way round from 12."""
        return self._centre + reach * self._radius * _direction(turns)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt

    @override
    def render_gray(self) -> np.ndarray:
        now = datetime.now()
        hours = (now.hour % 12 + now.minute / 60) / 12
        minutes = now.minute / 60
        frame = self._face.copy()
        draw.line(frame, self._centre, self._point(hours, _HOUR_HAND), self._line)
        draw.line(frame, self._centre, self._point(minutes, _MINUTE_HAND), self._line)
        return frame
