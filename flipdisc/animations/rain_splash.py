"""Rain on a pool, seen from directly above.

Only the impacts show: each drop makes a splash (one dot, or a 2x2 block for a
big drop) and then a one-pixel ring that expands by whole pixels until it
reaches that drop's own maximum radius and vanishes. Maximum radii are drawn
from a normal distribution, so most rings die young and the surface stays
readable instead of filling with full-screen circles.
"""

from dataclasses import dataclass, field
from typing import override

import numpy as np

from .base import Animation, register_animation
from .cadence import Cadence
from .params import Param

# A big drop pushes more water, so its ring travels further on average
_BIG_RING_SCALE = 1.5


@dataclass
class _Ripple:
    cx: float  # ring centre; a big splash is centred between pixels
    cy: float
    big: bool
    max_radius: int
    radius: int = 0  # 0 = the splash itself, before any ring
    cadence: Cadence = field(default_factory=Cadence)


@register_animation("rain_splash")
class RainSplash(Animation):
    """Splashes and expanding ripple rings from rain falling on still water."""

    PARAMS = (
        Param("drops_per_second", float, 2.0, min=0, max=50, step=0.5, unit="/s"),
        Param("big_drop_chance", float, 0.1, min=0, max=1, step=0.05),
        Param("ring_speed", float, 4.0, min=1, max=40, step=1, unit="px/s"),
        Param("ring_size", float, 5.0, min=1, max=30, step=0.5, unit="px"),
        Param("ring_size_spread", float, 1.5, min=0, max=10, step=0.5, unit="px"),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._ripples: list[_Ripple] = []
        self._ys, self._xs = np.mgrid[0:height, 0:width].astype(np.float32)

    def _add_ripple(self, x: int, y: int, big: bool, max_radius: int) -> None:
        """Start a splash whose top-left dot is at (x, y)."""
        offset = 0.5 if big else 0.0
        self._ripples.append(_Ripple(x + offset, y + offset, big, max_radius))

    def _spawn(self) -> None:
        big = np.random.random() < self.params["big_drop_chance"]
        size = 2 if big else 1
        x = np.random.randint(0, max(1, self.width - size + 1))
        y = np.random.randint(0, max(1, self.height - size + 1))
        mean = self.params["ring_size"] * (_BIG_RING_SCALE if big else 1.0)
        max_radius = max(
            1, round(np.random.normal(mean, self.params["ring_size_spread"]))
        )
        self._add_ripple(x, y, big, max_radius)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt

        speed = self.params["ring_speed"]
        for ripple in self._ripples:
            ripple.radius += ripple.cadence.advance(speed, dt)
        self._ripples = [r for r in self._ripples if r.radius <= r.max_radius]

        # Rain is random, so drops arrive as a Poisson process rather than on
        # an even Cadence; each ring still expands with its own even rhythm.
        for _ in range(np.random.poisson(self.params["drops_per_second"] * dt)):
            self._spawn()

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        for ripple in self._ripples:
            if ripple.radius == 0:
                x, y = int(ripple.cx), int(ripple.cy)
                size = 2 if ripple.big else 1
                frame[y : y + size, x : x + size] = 1.0
                continue
            # A big splash's ring starts just outside its 2x2 block
            radius = ripple.radius + (0.5 if ripple.big else 0.0)
            dist = np.hypot(self._xs - ripple.cx, self._ys - ripple.cy)
            frame[np.abs(dist - radius) < 0.5] = 1.0
        return frame

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._ripples.clear()
