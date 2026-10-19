"""Granular material poured onto the floor, building a pile that spreads.

A stream of grains falls from the pour point, accelerating under gravity, and
lands on the pile. Settled grains are stacked per column: a grain on top of a
column rolls one column sideways when the pile's surface there is steeper than
the material's angle of repose, so the pile grows as a cone and slumps outward
as it builds. High friction gives a steep sand cone; low friction lets grains
roll away like marbles.

Each grain lives for ``lifespan`` seconds (±25%) and then vanishes where it
is; the grains above it drop into the gap, so the pile reaches a steady size
and slowly churns instead of filling the display.

The spout stays at the top and sweeps from side to side on a sine wave
around ``pour_position``, laying down a moving ridge of piles.
"""

import math
from dataclasses import dataclass
from typing import override

import numpy as np

from .base import Animation, register_animation
from .cadence import Cadence
from .params import Param

# How far ahead a grain looks for somewhere lower. Looking one column ahead
# only, the gentlest possible slope is one step per column (45°); looking
# further lets low-friction material settle flatter than that.
_SLOPE_BASELINE = 4

# Angle of repose at friction 0 (marbles) and 1 (coarse, damp sand)
_MIN_REPOSE_DEG = 5.0
_MAX_REPOSE_DEG = 60.0

# Grains don't all expire on schedule, so the pile erodes gradually
_LIFESPAN_JITTER = 0.25

# Fraction of its fall speed a grain keeps when it glances off the pile
_DEFLECT_SPEED_KEPT = 0.5

# Speed grains leave the spout. Starting from rest they would crawl through
# the top rows and bunch up there, making the stream look far heavier than
# the pour rate.
_SPOUT_SPEED = 5.0  # px/s

# How far the spout sweeps either side of pour_position, as a fraction of the
# display width (clipped at the edges)
_SWEEP_AMPLITUDE = 0.4


@dataclass(slots=True)
class _FallingGrain:
    x: int
    y: float  # rows from the top; rasterized, so it moves continuously
    vy: float


@register_animation("sandpile")
class Sandpile(Animation):
    """A poured stream of grains building a pile that slumps and spreads."""

    PARAMS = (
        Param("pour_rate", float, 5.0, min=0, max=60, step=1, unit="grains/s"),
        Param("friction", float, 0.45, min=0, max=1, step=0.05),
        Param("gravity", float, 10.0, min=5, max=500, step=5, unit="px/s²"),
        Param("lifespan", float, 50.0, min=1, max=600, step=1, unit="s"),
        Param("pour_position", float, 0.5, min=0, max=1, step=0.05),
        # Full side-to-side cycles per second; 0 holds the spout still
        Param("sweep_speed", float, 0.1, min=0, max=1, step=0.01, unit="Hz"),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        # Expiry time of each settled grain, per column, bottom first
        self._columns: list[list[float]] = [[] for _ in range(width)]
        self._falling: list[_FallingGrain] = []
        self._pour = Cadence()
        self._roll = Cadence()
        self._sweep_phase = 0.0

    @property
    def _repose_slope(self) -> float:
        span = _MAX_REPOSE_DEG - _MIN_REPOSE_DEG
        degrees = _MIN_REPOSE_DEG + self.params["friction"] * span
        return math.tan(math.radians(degrees))

    def _expire(self) -> None:
        now = self.current_time
        for column in self._columns:
            if column and min(column) <= now:
                column[:] = [t for t in column if t > now]

    def _land(self, x: int) -> None:
        column = self._columns[x]
        if len(column) >= self.height:
            return  # the pile has reached the top; the grain is lost
        jitter = 1 + _LIFESPAN_JITTER * (2 * np.random.random() - 1)
        column.append(self.current_time + self.params["lifespan"] * jitter)

    def _fall(self, dt: float) -> None:
        gravity = self.params["gravity"]
        still_falling = []
        for grain in self._falling:
            grain.vy += gravity * dt
            grain.y += grain.vy * dt
            surface = self.height - len(self._columns[grain.x])
            if grain.y < surface - 1:
                still_falling.append(grain)
                continue
            # A grain hitting a slope steeper than it can rest on glances off
            # downhill and keeps going, one column per frame
            side = self._downhill(grain.x, len(self._columns[grain.x]) + 1)
            if side:
                grain.x += side
                grain.vy *= _DEFLECT_SPEED_KEPT
                still_falling.append(grain)
            else:
                self._land(grain.x)
        self._falling = still_falling

    def _spout_x(self) -> int:
        offset = _SWEEP_AMPLITUDE * math.sin(self._sweep_phase)
        position = min(max(self.params["pour_position"] + offset, 0.0), 1.0)
        return round(position * (self.width - 1))

    def _pour_grains(self, dt: float) -> None:
        count = self._pour.advance(self.params["pour_rate"], dt)
        x = self._spout_x()
        gravity = self.params["gravity"]
        for i in range(count):
            # Several grains in one frame left the spout at different moments
            # within it, so spread them along the stream instead of stacking
            # them on one pixel.
            elapsed = i * dt / count
            y = _SPOUT_SPEED * elapsed + 0.5 * gravity * elapsed**2
            self._falling.append(_FallingGrain(x, y, _SPOUT_SPEED + gravity * elapsed))

    def _slope(self, x: int, height: int, direction: int) -> float:
        """How steeply a grain on top of a ``height`` stack in column x could
        descend one way: its drop per column to the lowest-looking point
        within ``_SLOPE_BASELINE`` columns."""
        room = x if direction < 0 else self.width - 1 - x
        resting_row = height - 1  # the grain's own level, counted from the floor
        return max(
            (resting_row - len(self._columns[x + direction * reach])) / reach
            for reach in range(1, min(_SLOPE_BASELINE, room) + 1)
        )

    def _downhill(self, x: int, height: int) -> int:
        """Which way a grain on top of a surface at ``height`` would roll.

        Returns -1 or 1 when the surface is steeper than the angle of repose
        on that side (the steeper side if both), else 0.
        """
        best, steepest = 0, self._repose_slope
        for direction in np.random.permutation((-1, 1)).tolist():
            side = x + direction
            if not 0 <= side < self.width or len(self._columns[side]) >= height:
                continue
            slope = self._slope(x, height, direction)
            if slope > steepest:
                best, steepest = direction, slope
        return best

    def _roll_grains(self) -> None:
        """Move each over-steep column's top grain one column downhill."""
        # Friction also makes an unstable grain slower to get going
        roll_chance = 1 - 0.5 * self.params["friction"]
        arrived: set[int] = set()
        for x in np.random.permutation(self.width).tolist():
            height = len(self._columns[x])
            if height == 0 or x in arrived:
                continue
            side = self._downhill(x, height)
            if side and np.random.random() < roll_chance:
                self._columns[x + side].append(self._columns[x].pop())
                arrived.add(x + side)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._expire()
        self._fall(dt)
        self._sweep_phase += 2 * math.pi * self.params["sweep_speed"] * dt
        self._pour_grains(dt)
        # A grain tipping off a ledge falls one pixel in sqrt(2 / g) seconds;
        # rolling one column takes about that long
        roll_rate = math.sqrt(2 * self.params["gravity"])
        for _ in range(self._roll.advance(roll_rate, dt)):
            self._roll_grains()

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        for x, column in enumerate(self._columns):
            if column:
                frame[self.height - len(column) :, x] = 1.0
        for grain in self._falling:
            row = int(grain.y)
            if 0 <= row < self.height:
                frame[row, grain.x] = 1.0
        return frame

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        for column in self._columns:
            column.clear()
        self._falling.clear()
        self._pour.reset()
        self._roll.reset()
        self._sweep_phase = 0.0
