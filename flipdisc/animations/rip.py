"""Sheets torn off one after another.

The display is a stack of sheets, alternately black and white. Each rip tears
the top sheet along a straight line at a random angle and place, right across
the display, and pulls the two halves apart from the middle of the tear until
they're gone, showing the sheet beneath. The display rests on that sheet for
``pause`` seconds, then the next rip begins.

The hole is an eye shape. Each half's torn edge is half an ellipse, widest
where the tear is grabbed (its middle) and closing where the tear runs off the
display. As the halves are pulled apart the edges curve more, but the sheet is
stiff: the curve levels off at ``bulge`` and from then on the halves keep that
shape as they fly off the display. The pull starts slowly and accelerates, so
a rip opens as a sliver and is gone a few frames later.

Sizes are relative to the display's smaller dimension, so the animation looks
the same on any display; the first crack is a line, so it widens more slowly
(see ``scaling.py``).
"""

import math
from typing import override

import numpy as np

from flipdisc.gfx.draw import pixel_centres

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Clock comparisons allow for floating-point error in the frame times summed
# to reach them, so a cycle always takes the same number of frames
_EPS = 1e-6

# The tear crosses a random point in the middle of the display, this fraction
# of its width and height
_CROSSING_REGION = 0.5

# From its first frame the tear is a crack this wide (in dots on the 28-dot
# design display), a line of dots right across the display
_CRACK_WIDTH = 1.0


class _Tear:
    """One tear's geometry, measured for every dot."""

    def __init__(
        self, profile: np.ndarray, distance: np.ndarray, pull: float, crack: float
    ):
        # Each dot's share of the full bulge (1 level with the grab point,
        # 0 at the ends of the tear), and its distance from the tear line
        self.profile = profile
        self.distance = distance
        # How far the halves' straight part must move to clear every dot
        self.pull = pull
        # How far either side of the tear line the first crack reaches
        self.crack = crack

    def opening(self, progress: float, bulge: float) -> np.ndarray:
        """Which dots the hole has uncovered ``progress`` of the way through
        the rip (0 to 1), when the edges curve at most ``bulge`` px."""
        # How far the grab point has been pulled from the tear line
        grabbed = (self.pull + bulge) * progress**2
        # The edges curve more as they're pulled, levelling off at the bulge;
        # the rest of the pull moves the whole edge
        curve = bulge * math.tanh(grabbed / bulge) if bulge > 0 else 0.0
        edge = curve * self.profile + (grabbed - curve)
        return self.distance < np.maximum(edge, self.crack)


@register_animation("rip")
class Rip(Animation):
    """Black and white sheets torn off the display one after another."""

    PARAMS = (
        # From the first sign of the tear to the sheet being gone
        Param("rip_time", float, 0.4, min=0.1, max=5, step=0.05, unit="s"),
        # How long the display rests on each new sheet
        Param("pause", float, 0.5, min=0, max=10, step=0.1, unit="s"),
        # How far the middle of each torn edge leads its ends once the sheet's
        # stiffness stops it curving more, as a fraction of the display; 0
        # pulls the halves apart as straight edges
        Param("bulge", float, 0.3, min=0, max=1, step=0.05),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)
        self._crack = self.scale.line(_CRACK_WIDTH) / 2
        # Centres (x, y) of the dots
        self._dots = np.stack(pixel_centres(self.width, self.height), axis=-1)
        self._restart()

    def _restart(self) -> None:
        # The top sheet's colour (0 black, 1 white), and the time since it was
        # uncovered
        self._top = 0.0
        self._clock = 0.0
        self._tear: _Tear | None = None

    def _new_tear(self) -> _Tear:
        """A tear in a random direction through the middle of the display."""
        size = np.array([self.width, self.height], dtype=float)
        margin = (1 - _CROSSING_REGION) / 2
        point = np.random.uniform(margin, 1 - margin, 2) * size
        angle = np.random.uniform(0, math.pi)
        along = np.array([math.cos(angle), math.sin(angle)])

        # Where the line enters and leaves the display; it's grabbed midway
        with np.errstate(divide="ignore"):
            bounds = np.sort(np.stack((-point, size - point)) / along, axis=0)
        enter, leave = bounds[0].max(), bounds[1].min()
        middle = point + along * (enter + leave) / 2

        offsets = self._dots - middle
        s = offsets @ along
        h = offsets @ np.array([-along[1], along[0]])
        # The ellipse closes where the tear leaves the display
        half_length = (leave - enter) / 2
        return _Tear(
            profile=np.sqrt(np.clip(1 - (s / half_length) ** 2, 0, None)),
            distance=np.abs(h),
            pull=np.abs(h).max() + 0.5,
            crack=self._crack,
        )

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._clock += dt
        pause = self.params["pause"]
        cycle = pause + self.params["rip_time"]
        if self._clock >= cycle - _EPS:
            # The sheet is gone; the one beneath is now on top
            self._clock = max(0.0, self._clock - cycle)
            self._top = 1.0 - self._top
            self._tear = None
        if self._tear is None and self._clock > pause + _EPS:
            self._tear = self._new_tear()

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.full((self.height, self.width), self._top, dtype=np.float32)
        if self._tear is None:
            return frame
        progress = (self._clock - self.params["pause"]) / self.params["rip_time"]
        bulge = self.params["bulge"] * self.scale.short_side
        hole = self._tear.opening(min(max(progress, 0.0), 1.0), bulge)
        frame[hole] = 1.0 - self._top
        return frame

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._restart()
