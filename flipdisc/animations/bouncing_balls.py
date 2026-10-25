"""Balls bouncing off each other and the walls.

A fixed number of balls, all the same size, fly around the display with no
gravity or friction. At ``elasticity`` 1 (the default) every collision is
perfectly elastic and the total kinetic energy never changes. The balls all
start at the same speed; collisions soon spread their speeds out, so at any
moment some are darting about and others drifting, but no ball is slower than
the rest on average.

Each impact squashes the balls involved for a moment, flattening them along
the line of impact and bulging them sideways (keeping their area), harder hits
more. It's only drawn: the physics treats every ball as a rigid disc, so the
squash costs no energy. A 4-dot ball has too few dots to show a slight squash,
so on a 28-dot display only hard hits show.

All the balls are one size because balls of different sizes have different
masses, and elastic collisions even out energy, not speed: a ball 16 times
heavier ends up with the same energy on average, and so moves 4 times slower.

Speeds are relative to the display's smaller dimension, so the motion looks
the same on any display; the balls grow more slowly than the display, so a
bigger one shows more of them in finer detail (see ``scaling.py``).
"""

import math
from typing import Any, override

import numpy as np

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Ball diameters in dots on the 28-dot design display
_DIAMETERS = frozendict(small=1, large=4)

# The furthest any ball moves in one physics substep, as a fraction of its
# radius, so balls never pass through each other
_MAX_MOVE = 0.5

# Collisions are only looked for between pairs of balls that were within this
# many substep moves of touching when the list of pairs was last made
_MARGIN_MOVES = 12

# An impact this fast, in display sizes per second, squashes a ball by the
# full ``squash``; slower impacts squash it proportionally less
_FULL_SQUASH_SPEED = 0.5

# A squashed ball springs back exponentially with this time constant
_SQUASH_RECOVERY = 0.05  # s

# Below this squash a ball is drawn round
_ROUND = 0.01

# Placing balls at random tries this many spots for each before giving up on
# it (only when the display is too crowded for the requested count)
_PLACEMENT_TRIES = 500


@register_animation("bouncing_balls")
class BouncingBalls(Animation):
    """Equal balls colliding elastically in a box."""

    PARAMS = (
        # Changing count or size restarts with the balls in new places. Balls
        # are placed at random, which fits 20 large balls on a 28-dot display
        # but rarely more than 30; any that don't fit are left out.
        Param("count", int, 10, min=0, max=60),
        Param("size", str, "large", choices=tuple(_DIAMETERS)),
        # Every ball starts at this speed in a random direction, in display
        # sizes per second; changing it relaunches the balls from where they
        # are
        Param("speed", float, 0.3, min=0, max=3, step=0.05, unit="displays/s"),
        # Coefficient of restitution of every collision, ball or wall: 1 keeps
        # all the energy, 0 stops the balls dead along the line of impact
        Param("elasticity", float, 1.0, min=0, max=1, step=0.05),
        # How much a hard impact flattens a ball, as a fraction of its
        # diameter; 0 keeps every ball round
        Param("squash", float, 0.3, min=0, max=0.5, step=0.05),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)

        # Centre (x, y) and velocity of each ball, in px and px/s
        self._pos = np.zeros((0, 2))
        self._vel = np.zeros((0, 2))
        # How squashed each ball is (a fraction of its diameter), and the unit
        # direction (x, y) from its centre to what it hit
        self._squash = np.zeros(0)
        self._squash_dir = np.zeros((0, 2))
        self._restart()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _restart(self) -> None:
        self._diameter = self.scale.dots(_DIAMETERS[self.params["size"]])
        self._radius = self._diameter / 2
        # Where a ball's centre stops at the walls, as (x, y)
        self._wall_high = np.array([self.width, self.height]) - self._radius

        placed: list[tuple[float, float]] = []
        for _ in range(self.params["count"]):
            spot = self._free_spot(placed)
            if spot is not None:
                placed.append(spot)
        self._pos = np.array(placed).reshape(-1, 2)
        self._squash = np.zeros(len(self._pos))
        self._squash_dir = np.zeros((len(self._pos), 2))
        self._launch()

    def _free_spot(
        self, placed: list[tuple[float, float]]
    ) -> tuple[float, float] | None:
        """A random centre where a ball fits inside the walls without touching
        any placed ball, or None if none was found."""
        r = self._radius
        for _ in range(_PLACEMENT_TRIES):
            x = np.random.uniform(r, max(r, self.width - r))
            y = np.random.uniform(r, max(r, self.height - r))
            if all(math.hypot(x - px, y - py) >= 2 * r for px, py in placed):
                return x, y
        return None

    def _launch(self) -> None:
        """Send every ball off at ``speed`` in a random direction."""
        speed = self.params["speed"] * self.scale.short_side
        angle = np.random.uniform(0, 2 * math.pi, len(self._pos))
        self._vel = speed * np.column_stack((np.cos(angle), np.sin(angle)))

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _bounce_off_walls(self) -> None:
        elasticity = self.params["elasticity"]
        low, high = self._radius, self._wall_high
        hit = ((self._pos < low) & (self._vel < 0)) | (
            (self._pos > high) & (self._vel > 0)
        )
        if hit.any():
            # Squash against whichever wall was hit harder (a corner hits two
            # at once); the ball is still heading into it
            impact = np.where(hit, np.abs(self._vel), 0.0)
            axis = impact.argmax(axis=1)
            directions = np.eye(2)[axis] * np.sign(self._vel)
            self._squash_from(impact[np.arange(len(axis)), axis], directions)
        self._vel[hit] *= -elasticity
        np.clip(self._pos, low, high, out=self._pos)

    def _nearby_pairs(self, travel: float) -> tuple[np.ndarray, np.ndarray]:
        """Indices (i, j), i < j, of every pair of balls that could touch
        once each has moved up to ``travel`` px."""
        apart = self._pos[None, :, :] - self._pos[:, None, :]
        distance = np.hypot(apart[..., 0], apart[..., 1])
        return np.nonzero(np.triu(distance < self._diameter + 2 * travel, k=1))

    def _collide_balls(self, first: np.ndarray, second: np.ndarray) -> None:
        """Resolve every touching pair among the candidates (first, second).

        Pairs are resolved one after another, each with the velocities left by
        the one before, so a ball touching two others at once still conserves
        energy exactly at elasticity 1.
        """
        offsets = self._pos[second] - self._pos[first]
        touching = np.hypot(offsets[:, 0], offsets[:, 1]) < self._diameter
        if not touching.any():
            return

        elasticity = self.params["elasticity"]
        pos, vel = self._pos, self._vel
        pairs = zip(first[touching].tolist(), second[touching].tolist(), strict=True)
        for i, j in pairs:
            dx, dy = (pos[j] - pos[i]).tolist()
            gap = math.hypot(dx, dy)
            nx, ny = (dx / gap, dy / gap) if gap > 1e-9 else (1.0, 0.0)

            # Push them apart so they just touch
            push = (self._diameter - gap) / 2
            pos[i] -= (nx * push, ny * push)
            pos[j] += (nx * push, ny * push)

            rx, ry = (vel[j] - vel[i]).tolist()
            closing = rx * nx + ry * ny
            if closing >= 0:
                continue  # already separating
            # Equal masses share the impulse equally; at elasticity 1 they
            # swap their velocities along the line between their centres
            kick = (1 + elasticity) * closing / 2
            vel[i] += (nx * kick, ny * kick)
            vel[j] -= (nx * kick, ny * kick)
            self._squash_ball(i, -closing, nx, ny)
            self._squash_ball(j, -closing, -nx, -ny)

    def _squash_amount(self, impact: np.ndarray | float) -> np.ndarray | float:
        """How far an impact at ``impact`` px/s squashes a ball."""
        full_speed = _FULL_SQUASH_SPEED * self.scale.short_side
        return self.params["squash"] * np.minimum(impact / full_speed, 1.0)

    def _squash_ball(self, i: int, impact: float, nx: float, ny: float) -> None:
        """Squash ball i against something in direction (nx, ny), unless it's
        already squashed more."""
        amount = float(self._squash_amount(impact))
        if amount > self._squash[i]:
            self._squash[i] = amount
            self._squash_dir[i] = (nx, ny)

    def _squash_from(self, impact: np.ndarray, directions: np.ndarray) -> None:
        """``_squash_ball`` for every ball at once (zero impact: no change)."""
        amount = self._squash_amount(impact)
        more = amount > self._squash
        self._squash[more] = amount[more]
        self._squash_dir[more] = directions[more]

    def _fastest(self) -> float:
        return float(np.hypot(self._vel[:, 0], self._vel[:, 1]).max())

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if len(self._pos) == 0:
            return
        max_move = _MAX_MOVE * self._radius
        # The list of pairs that could collide is remade before any ball has
        # moved far enough to reach a pair it leaves out
        margin = _MARGIN_MOVES * max_move
        first, second = self._nearby_pairs(margin)
        anchor = self._pos.copy()

        remaining = dt
        while remaining > 0:
            # A collision can speed a ball up, so the substep is sized afresh
            # from the fastest ball each time
            h = min(remaining, max_move / max(self._fastest(), 1e-9))
            remaining -= h
            self._squash *= math.exp(-h / _SQUASH_RECOVERY)
            self._pos += self._vel * h
            if len(first):
                self._collide_balls(first, second)
            self._bounce_off_walls()

            moved = self._pos - anchor
            if np.hypot(moved[:, 0], moved[:, 1]).max() + max_move > margin:
                first, second = self._nearby_pairs(margin)
                anchor = self._pos.copy()

    # ------------------------------------------------------------------
    # Animation interface
    # ------------------------------------------------------------------

    @override
    def render_gray(self) -> np.ndarray:
        """Draw each ball as an ellipse of dots: a disc when it isn't squashed,
        flattened along its squash direction when it is."""
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        if len(self._pos) == 0:
            return frame
        r = self._radius
        # Snapping the centre so the ball's top-left corner is on a dot keeps
        # an unsquashed ball the same shape wherever it is, so it never
        # flickers as it moves
        centre = np.rint(self._pos - r) + r
        across = r * (1 - self._squash)  # along the squash direction
        along = r / (1 - self._squash)  # perpendicular, keeping the area
        # The flattened side stays where it touched; the far side comes in
        centre += self._squash_dir * (r - across)[:, None]

        # Every dot within reach of the widest a ball can be drawn
        reach = math.ceil(r / (1 - self.params["squash"]))
        offsets = np.arange(-reach, reach + 1)
        corner = np.floor(centre).astype(np.intp)
        shape = (len(centre), len(offsets), len(offsets))
        cols = np.broadcast_to(corner[:, 0, None, None] + offsets, shape)
        rows = np.broadcast_to(corner[:, 1, None, None] + offsets[:, None], shape)
        dx = cols + 0.5 - centre[:, 0, None, None]
        dy = rows + 0.5 - centre[:, 1, None, None]

        nx = self._squash_dir[:, 0, None, None]
        ny = self._squash_dir[:, 1, None, None]
        u = (dx * nx + dy * ny) / across[:, None, None]
        v = (dy * nx - dx * ny) / along[:, None, None]
        # A ball that has all but sprung back is drawn as the plain disc, so
        # it settles on exactly the shape it had before the hit
        round_ = self._squash[:, None, None] < _ROUND
        lit = np.where(round_, dx**2 + dy**2 <= r**2, u**2 + v**2 <= 1)
        lit &= (rows >= 0) & (rows < self.height) & (cols >= 0) & (cols < self.width)
        frame[rows[lit], cols[lit]] = 1.0
        return frame

    @override
    def on_configure(self, **params: Any) -> None:
        if "count" in params or "size" in params:
            self._restart()
        elif "speed" in params:
            self._launch()

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._restart()
