"""A black hole swallowing a whirlpool of particle streaks.

Inspired by Yudho (https://yudho.xyz).

Particles orbit the centre on a tilted disc, faster the closer they are
(Keplerian, angular speed ~ r^-1.5), and drift slowly inward. One that
reaches the hole is replaced by a new one at the rim, so the disc never
empties. Each lit particle is drawn as a short streak trailing behind it.

The spiral arms are density waves, not material: a log-spiral pattern turns
rigidly at the rim's orbital speed, and a particle is lit mostly while it
passes through an arm (a few stay lit between them, as haze). Particles
overtake the pattern and stream through it, so the arms keep their shape
instead of winding up. Close to the hole every particle is lit, which makes a
bright inner ring.

The disc is tilted with its near side at the bottom, so the dark shadow
hides the far side of the disc behind the hole while the near side passes in
front of it.

Distances are in units of half the display's shorter side; the disc reaches
past the corners. Each particle and each point of its streak is one dot, so a
bigger display shows more of them at the same density; inflow is a speed in
design dots, so it grows with the display.
"""

import math
from typing import Any, override

import numpy as np

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Angular speed is `spin` at this radius
_REFERENCE_RADIUS = 0.5

# Particles within this many hole radii are always lit
_INNER_RING = 1.6

# Raising the wave to this power narrows the arms and darkens the gaps
_ARM_SHARPNESS = 3.0

# Share of particles lit between the arms, a faint haze of streaks
_HAZE = 0.1

# Longest trail, in dots
_MAX_TRAIL = 6


@register_animation("black_hole")
class BlackHole(Animation):
    """Particle streaks spiralling into a black hole."""

    PARAMS = (
        # Particles per pixel of display area
        Param("density", float, 0.6, min=0.05, max=2, step=0.05),
        # Angular speed halfway to the edge; positive is counterclockwise
        Param("spin", float, 0.4, min=-3, max=3, step=0.05, unit="rad/s"),
        Param("inflow", float, 0.3, min=0, max=5, step=0.1, unit="px/s"),
        Param("arms", int, 2, min=1, max=6),
        # How tightly the arms wind; 0 is straight spokes
        Param("winding", float, 2.5, min=0, max=8, step=0.25),
        # Radius of the shadow, as a fraction of half the shorter side
        Param("hole_size", float, 0.18, min=0, max=0.6, step=0.02),
        # 0 is face on, 90 edge on
        Param("tilt", float, 35, min=0, max=80, step=5, unit="°"),
        Param("trail", int, 2, min=1, max=_MAX_TRAIL, unit="px"),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)
        # Dots per unit of distance
        self._unit = self.scale.short_side / 2
        # The disc reaches the corners, plus the longest trail
        self._rim = (math.hypot(self.width, self.height) / 2 + _MAX_TRAIL) / self._unit
        self._pattern_angle = 0.0
        self._init_particles()

    # ------------------------------------------------------------------
    # Particles
    # ------------------------------------------------------------------

    def _target_count(self) -> int:
        return max(1, round(self.params["density"] * self.width * self.height))

    def _inner_radius(self) -> float:
        # A floor keeps angular speed finite with no hole
        return max(self.params["hole_size"], 0.05)

    def _init_particles(self) -> None:
        n = self._target_count()
        # Uniform in radius is the steady state of a constant inflow
        self._r = np.random.uniform(self._inner_radius(), self._rim, n)
        self._theta = np.random.uniform(0.0, 2 * math.pi, n)
        # How deep into an arm a particle must be before it lights
        self._lit_at = np.random.random(n)

    def _resize(self) -> None:
        n = self._target_count()
        old = len(self._r)
        if n <= old:
            self._r = self._r[:n]
            self._theta = self._theta[:n]
            self._lit_at = self._lit_at[:n]
            return
        extra = n - old
        self._r = np.concatenate(
            [self._r, np.random.uniform(self._inner_radius(), self._rim, extra)]
        )
        self._theta = np.concatenate(
            [self._theta, np.random.uniform(0.0, 2 * math.pi, extra)]
        )
        self._lit_at = np.concatenate([self._lit_at, np.random.random(extra)])

    def _angular_speed(self, r: np.ndarray | float) -> np.ndarray | float:
        return self.params["spin"] * (_REFERENCE_RADIUS / r) ** 1.5

    # ------------------------------------------------------------------
    # Animation interface
    # ------------------------------------------------------------------

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self._theta = (self._theta + self._angular_speed(self._r) * dt) % (2 * math.pi)
        self._r -= self.scale.length(self.params["inflow"]) / self._unit * dt
        self._pattern_angle += self._angular_speed(self._rim) * dt

        swallowed = self._r < self._inner_radius()
        n = int(swallowed.sum())
        if n:
            self._r[swallowed] = self._rim
            self._theta[swallowed] = np.random.uniform(0.0, 2 * math.pi, n)

    def _lit(self) -> np.ndarray:
        r, theta = self._r, self._theta
        arms = self.params["arms"]
        wave = np.cos(
            arms * (theta - self._pattern_angle) - self.params["winding"] * np.log(r)
        )
        inner = r < self._inner_radius() * _INNER_RING
        arm = (0.5 + 0.5 * wave) ** _ARM_SHARPNESS
        return inner | (_HAZE + (1 - _HAZE) * arm > self._lit_at)

    @override
    def render_gray(self) -> np.ndarray:
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        lit = self._lit()
        r = self._r[lit]
        theta = self._theta[lit]

        # Streak points one dot apart along the orbit, trailing behind
        direction = 1.0 if self.params["spin"] >= 0 else -1.0
        back = np.arange(self.params["trail"])[:, None] / (r * self._unit)
        theta = theta - direction * back
        r = np.broadcast_to(r, theta.shape)

        squash = math.cos(math.radians(self.params["tilt"]))
        x = r * np.cos(theta)
        y = -r * np.sin(theta) * squash  # screen y points down

        # The shadow hides the far half of the disc (the top) behind it
        hole = self.params["hole_size"]
        hidden = (np.hypot(x, y) < hole) & (y < 0)

        col = np.floor(self.width / 2 + x * self._unit).astype(np.intp)
        row = np.floor(self.height / 2 + y * self._unit).astype(np.intp)
        shown = (
            ~hidden & (col >= 0) & (col < self.width) & (row >= 0) & (row < self.height)
        )
        frame[row[shown], col[shown]] = 1.0
        return frame

    @override
    def on_configure(self, **params: Any) -> None:
        if "density" in params:
            self._resize()
        if "hole_size" in params:
            # Anything now inside the hole moves to its edge, to be swallowed
            # as it drifts in
            self._r = np.maximum(self._r, self._inner_radius())

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._pattern_angle = 0.0
        self._init_particles()
