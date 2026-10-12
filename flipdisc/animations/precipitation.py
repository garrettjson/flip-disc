"""Precipitation particle effects for weather animations.

SnowEffect renders falling snowflake particles over a cloud icon.
RainEffect renders falling rain streaks over a cloud icon.
LightningEffect renders animated lightning bolts below a cloud icon.
"""

from __future__ import annotations

import enum
import random
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .cadence import Cadence

# Snowflake shapes: tuples of (row, col) offsets from the particle origin.
# 1-piece single pixel
_SNOW_1 = ((0, 0),)
# 2-piece diagonal pairs
_SNOW_2A = ((0, 1), (1, 0))
_SNOW_2B = ((0, 0), (1, 1))
# 3-piece zigzag variants
_SNOW_3A = ((0, 1), (1, 0), (1, 2))
_SNOW_3B = ((0, 0), (0, 2), (1, 1))
_SNOW_3C = ((0, 0), (1, 1), (2, 0))
_SNOW_3D = ((0, 1), (1, 0), (2, 1))

_SNOW_SHAPES = [_SNOW_1, _SNOW_2A, _SNOW_2B, _SNOW_3A, _SNOW_3B, _SNOW_3C, _SNOW_3D]


@dataclass
class SnowParticle:
    x: int
    y: int
    shape: tuple[tuple[int, int], ...]


class SnowEffect:
    """Falling snow particle system.

    Spawns snowflake particles from the cloud base that fall straight down.
    Each snowflake is a small 2-3 pixel diagonal/zigzag shape.

    All particles advance together on a shared, even cadence (see
    ``Cadence``), so spacing between snowflakes stays perfectly uniform.
    """

    def __init__(
        self,
        cloud_cols_range: tuple[int, int],
        spawn_y: int,
        max_y: int,
        spawn_rate: float = 0.67,
        fall_speed: float = 2.0,
    ):
        self._col_min, self._col_max = cloud_cols_range
        self._spawn_y = spawn_y
        self._max_y = max_y
        self._spawn_rate = spawn_rate
        self._fall_speed = fall_speed
        self._particles: list[SnowParticle] = []
        self._spawn_cadence = Cadence()
        self._fall_cadence = Cadence()
        self._last_spawn_x: int | None = None
        self._rng = random.Random()

    def step(self, dt: float) -> None:
        # Advance all particles in lockstep
        fall = self._fall_cadence.advance(self._fall_speed, dt)
        if fall:
            for p in self._particles:
                p.y += fall

        # Cull off-screen particles
        self._particles = [p for p in self._particles if p.y <= self._max_y + 2]

        # Spawn new particles
        for _ in range(self._spawn_cadence.advance(self._spawn_rate, dt)):
            self._spawn_particle()

    def _spawn_particle(self) -> None:
        rng = self._rng
        shape = rng.choice(_SNOW_SHAPES)

        # Pick x within cloud range, at least 2px from last spawn
        col_min, col_max = self._col_min, self._col_max
        candidates = list(range(col_min, col_max + 1))
        if self._last_spawn_x is not None:
            filtered = [c for c in candidates if abs(c - self._last_spawn_x) >= 2]
            candidates = filtered or candidates

        x = rng.choice(candidates)
        self._last_spawn_x = x

        self._particles.append(SnowParticle(x=x, y=self._spawn_y, shape=shape))

    def render(self, canvas: np.ndarray) -> None:
        h, w = canvas.shape
        for p in self._particles:
            for dr, dc in p.shape:
                r = p.y + dr
                c = p.x + dc
                if 0 <= r < h and 0 <= c < w:
                    canvas[r, c] = max(canvas[r, c], 1.0)

    def configure(self, **params) -> None:
        if "spawn_rate" in params:
            self._spawn_rate = float(params["spawn_rate"])
        if "fall_speed" in params:
            self._fall_speed = float(params["fall_speed"])

    def reset(self) -> None:
        self._particles.clear()
        self._spawn_cadence.reset()
        self._fall_cadence.reset()
        self._last_spawn_x = None


# --- Rain shapes: vertical streaks (row, col) offsets ---
_RAIN_1 = ((0, 0),)
_RAIN_2 = ((0, 0), (1, 0))
_RAIN_3 = ((0, 0), (1, 0), (2, 0))

_RAIN_SHAPES_BY_SIZE = {
    1: [_RAIN_1],
    2: [_RAIN_1, _RAIN_2],
    3: [_RAIN_1, _RAIN_2, _RAIN_3],
}

# Per-WMO-code rain presets
WMO_RAIN_PRESETS: dict[int, dict] = {
    51: {"spawn_rate": 0.33, "fall_speed": 2.67, "droplet_size": 1},  # Light drizzle
    53: {"spawn_rate": 0.5, "fall_speed": 3.0, "droplet_size": 1},  # Moderate drizzle
    55: {"spawn_rate": 0.83, "fall_speed": 3.33, "droplet_size": 1},  # Dense drizzle
    56: {
        "spawn_rate": 0.33,
        "fall_speed": 2.33,
        "droplet_size": 1,
    },  # Light freezing drizzle
    57: {
        "spawn_rate": 0.83,
        "fall_speed": 3.0,
        "droplet_size": 1,
    },  # Dense freezing drizzle
    61: {"spawn_rate": 0.67, "fall_speed": 4.0, "droplet_size": 2},  # Slight rain
    63: {"spawn_rate": 1.0, "fall_speed": 4.67, "droplet_size": 2},  # Moderate rain
    65: {"spawn_rate": 1.67, "fall_speed": 6.0, "droplet_size": 3},  # Heavy rain
    66: {
        "spawn_rate": 0.67,
        "fall_speed": 3.67,
        "droplet_size": 2,
    },  # Light freezing rain
    67: {
        "spawn_rate": 1.5,
        "fall_speed": 5.33,
        "droplet_size": 3,
    },  # Heavy freezing rain
    80: {"spawn_rate": 0.83, "fall_speed": 4.67, "droplet_size": 2},  # Slight showers
    81: {"spawn_rate": 1.33, "fall_speed": 5.33, "droplet_size": 3},  # Moderate showers
    82: {"spawn_rate": 2.0, "fall_speed": 6.67, "droplet_size": 3},  # Violent showers
}


@dataclass
class RainParticle:
    x: int
    y: int
    shape: tuple[tuple[int, int], ...]


class RainEffect:
    """Falling rain particle system.

    Spawns rain droplets (vertical streaks) from the cloud base that fall
    straight down. Droplet sizes range from 1px to ``droplet_size`` px tall.

    All particles advance together on a shared, even cadence (see
    ``Cadence``), so spacing between droplets stays perfectly uniform.
    """

    def __init__(
        self,
        cloud_cols_range: tuple[int, int],
        spawn_y: int,
        max_y: int,
        spawn_rate: float = 1.0,
        fall_speed: float = 4.67,
        droplet_size: int = 2,
    ):
        self._col_min, self._col_max = cloud_cols_range
        self._spawn_y = spawn_y
        self._max_y = max_y
        self._spawn_rate = spawn_rate
        self._fall_speed = fall_speed
        self._droplet_size = max(1, min(3, droplet_size))
        self._particles: list[RainParticle] = []
        self._spawn_cadence = Cadence()
        self._fall_cadence = Cadence()
        self._last_spawn_x: int | None = None
        self._rng = random.Random()

    def step(self, dt: float) -> None:
        # Advance all particles in lockstep
        fall = self._fall_cadence.advance(self._fall_speed, dt)
        if fall:
            for p in self._particles:
                p.y += fall

        # Cull off-screen particles
        self._particles = [p for p in self._particles if p.y <= self._max_y + 2]

        # Spawn new particles
        for _ in range(self._spawn_cadence.advance(self._spawn_rate, dt)):
            self._spawn_particle()

    def _spawn_particle(self) -> None:
        rng = self._rng
        size = rng.randint(1, self._droplet_size)
        shapes = _RAIN_SHAPES_BY_SIZE[size]
        shape = rng.choice(shapes)

        # Pick x within cloud range, at least 2px from last spawn
        col_min, col_max = self._col_min, self._col_max
        candidates = list(range(col_min, col_max + 1))
        if self._last_spawn_x is not None:
            filtered = [c for c in candidates if abs(c - self._last_spawn_x) >= 2]
            candidates = filtered or candidates

        x = rng.choice(candidates)
        self._last_spawn_x = x

        self._particles.append(RainParticle(x=x, y=self._spawn_y, shape=shape))

    def render(self, canvas: np.ndarray) -> None:
        h, w = canvas.shape
        for p in self._particles:
            for dr, dc in p.shape:
                r = p.y + dr
                c = p.x + dc
                if 0 <= r < h and 0 <= c < w:
                    canvas[r, c] = max(canvas[r, c], 1.0)

    def configure(self, **params) -> None:
        if "spawn_rate" in params:
            self._spawn_rate = float(params["spawn_rate"])
        if "fall_speed" in params:
            self._fall_speed = float(params["fall_speed"])
        if "droplet_size" in params:
            self._droplet_size = max(1, min(3, int(params["droplet_size"])))

    def reset(self) -> None:
        self._particles.clear()
        self._spawn_cadence.reset()
        self._fall_cadence.reset()
        self._last_spawn_x = None


# --- Lightning effect ---

# Per-WMO-code thunderstorm presets
WMO_THUNDER_PRESETS: dict[int, dict] = {
    95: {"strike_interval": 900.0},  # Slight/moderate thunderstorm
    96: {"strike_interval": 540.0},  # Moderate with hail
    99: {"strike_interval": 180.0},  # Heavy with hail
}


class _LightningState(enum.Enum):
    IDLE = "idle"
    LEADER = "leader"
    FLASH_OFF = "flash_off"
    HOLDING = "holding"


class LightningEffect:
    """Animated lightning bolt effect.

    Generates procedural bolts using recursive midpoint displacement — the
    same technique used in video game lightning. A straight line is
    recursively subdivided, with the midpoint displaced horizontally at
    each level. At each subdivision there's a chance to fork, producing
    natural branching that tapers with depth. Strike cycle: bolt grows
    down row-by-row (LEADER) -> brief flash-off -> bolt reappears and
    holds (HOLDING) -> clears (IDLE).
    """

    def __init__(
        self,
        cloud_cols_range: tuple[int, int],
        spawn_y: int,
        max_y: int,
        strike_interval: float = 900.0,
        leader_speed: float = 10.0,
        text_row: int | None = None,
        text_max_col: int | None = None,
        display_width: int = 28,
    ):
        self._col_min, self._col_max = cloud_cols_range
        self._spawn_y = spawn_y
        self._max_y = max_y
        self._strike_interval = strike_interval
        self._leader_speed = leader_speed
        self._text_row = text_row
        self._text_max_col = text_max_col
        self._display_width = display_width
        self._rng = random.Random()

        self._state = _LightningState.IDLE
        self._timer: float = 0.0
        self._bolt: dict[int, set[int]] = {}
        self._bolt_max_row: int = max_y
        self._leader_row: float = 0.0
        self._leader_cadence = Cadence()
        self._first_strike = True

    def step(self, dt: float) -> None:
        self._timer += dt

        if self._state == _LightningState.IDLE:
            # First strike fires quickly; subsequent after brief pause
            wait = 3.0 if self._first_strike else 0.9
            if self._timer >= wait:
                self._bolt = self._generate_bolt()
                self._leader_row = float(self._spawn_y)
                self._leader_cadence.reset()
                self._state = _LightningState.LEADER
                self._timer = 0.0
                self._first_strike = False

        elif self._state == _LightningState.LEADER:
            self._leader_row += self._leader_cadence.advance(self._leader_speed, dt)
            if self._leader_row >= self._bolt_max_row:
                self._leader_row = float(self._bolt_max_row)
                self._state = _LightningState.FLASH_OFF
                self._timer = 0.0

        elif self._state == _LightningState.FLASH_OFF:
            if self._timer >= 0.3:
                self._state = _LightningState.HOLDING
                self._timer = 0.0

        elif self._state == _LightningState.HOLDING:
            if self._timer >= self._strike_interval:
                self._bolt = {}
                self._state = _LightningState.IDLE
                self._timer = 0.0

    # Bolt generation tuning — named so the algorithm reads clearly.
    _INITIAL_DISPLACEMENT = 5.0   # max horizontal jitter at top level
    _DISPLACEMENT_DECAY = 0.65    # each recursion level shrinks displacement
    _FORK_DISPLACEMENT_DECAY = 0.6
    _FORK_BASE_CHANCE = 0.55      # fork probability at depth 0
    _FORK_CHANCE_DECAY = 0.15     # subtracted per depth level
    _FORK_MAX_DEPTH = 4
    _REPEL_STRENGTH = 1.5         # bias (cols) pushing forks apart

    def _generate_bolt(self) -> dict[int, set[int]]:
        """Generate bolt using recursive midpoint displacement.

        Start with a straight vertical line, recursively subdivide by
        displacing the midpoint horizontally. At each subdivision there's
        a depth-decaying chance to fork, producing natural branching.
        Displacement is clamped to the half-span so Bresenham lines always
        stay 8-connected — no post-hoc cleanup needed.
        """
        rng = self._rng
        pixels: dict[int, set[int]] = defaultdict(set)
        col_min, col_max = self._col_min, self._col_max
        start_col = rng.randint(col_min + 2, col_max - 2)
        end_col = start_col + rng.randint(-4, 4)
        end_col = max(2, min(self._display_width - 3, end_col))

        self._subdivide(
            pixels,
            r0=self._spawn_y, c0=start_col,
            r1=self._max_y, c1=end_col,
            displacement=self._INITIAL_DISPLACEMENT, depth=0,
        )

        self._bolt_max_row = max(pixels.keys()) if pixels else self._max_y
        return dict(pixels)

    def _subdivide(
        self,
        pixels: dict[int, set[int]],
        r0: int, c0: int,
        r1: int, c1: int,
        displacement: float,
        depth: int,
        repel_col: float | None = None,
    ) -> None:
        """Recursively subdivide a segment via midpoint displacement.

        At each level the midpoint is displaced horizontally by a random
        amount. Displacement is clamped to the half-span so that the two
        child segments can always be rasterized as connected Bresenham
        lines (diagonal movement covers at most 1 col per row).

        ``repel_col`` biases displacement away from a sibling branch's
        column so that forked branches spread apart naturally.

        Base case: span <= 2 rows — rasterize directly.
        """
        rng = self._rng
        span = r1 - r0

        if span <= 2:
            self._rasterize(pixels, r0, c0, r1, c1)
            return

        # Clamp displacement so the midpoint stays within what Bresenham
        # can connect: half the span is the max diagonal reach.
        half_span = span // 2
        clamped_disp = min(displacement, float(half_span))

        mid_r = (r0 + r1) // 2
        mid_base = (c0 + c1) / 2

        # Repel bias: push midpoint away from sibling branch
        repel_bias = 0.0
        if repel_col is not None:
            delta = mid_base - repel_col
            if delta != 0:
                repel_bias = self._REPEL_STRENGTH * (1 if delta > 0 else -1)
            else:
                repel_bias = rng.choice(
                    [-self._REPEL_STRENGTH, self._REPEL_STRENGTH]
                )

        offset = rng.gauss(repel_bias, clamped_disp)
        # Hard clamp: midpoint can't jump further than half_span from base
        offset = max(-half_span, min(half_span, offset))
        mid_c = round(mid_base + offset)
        mid_c = max(1, min(self._display_width - 2, mid_c))

        # Fork: chance decays with depth, requires minimum span
        fork_chance = self._FORK_BASE_CHANCE - depth * self._FORK_CHANCE_DECAY
        do_fork = (
            depth < self._FORK_MAX_DEPTH
            and span >= 4
            and fork_chance > 0
            and rng.random() < fork_chance
        )

        if do_fork:
            fork_len = rng.randint(max(2, span // 4), max(3, span * 3 // 4))
            fork_r1 = min(self._max_y, mid_r + fork_len)
            # Push fork away from main segment's end column
            fork_direction = -1 if c1 >= mid_c else 1
            fork_offset = rng.randint(2, max(2, int(clamped_disp)))
            fork_c1 = mid_c + fork_direction * fork_offset
            fork_c1 = max(1, min(self._display_width - 2, fork_c1))

            self._subdivide(
                pixels, mid_r, mid_c, fork_r1, fork_c1,
                displacement=displacement * self._FORK_DISPLACEMENT_DECAY,
                depth=depth + 1,
                repel_col=float(c1),
            )

        # Recurse both halves of the main segment
        child_disp = displacement * self._DISPLACEMENT_DECAY
        self._subdivide(
            pixels, r0, c0, mid_r, mid_c,
            displacement=child_disp, depth=depth + 1,
        )
        self._subdivide(
            pixels, mid_r, mid_c, r1, c1,
            displacement=child_disp, depth=depth + 1,
        )

    def _rasterize(
        self,
        pixels: dict[int, set[int]],
        r0: int, c0: int,
        r1: int, c1: int,
    ) -> None:
        """Bresenham line rasterization between two points."""
        dr = abs(r1 - r0)
        dc = abs(c1 - c0)
        sr = 1 if r1 >= r0 else -1
        sc = 1 if c1 >= c0 else -1
        err = dr - dc
        r, c = r0, c0
        while True:
            if r <= self._max_y:
                self._place_pixel(pixels, r, c)
            if r == r1 and c == c1:
                break
            e2 = 2 * err
            if e2 > -dc:
                err -= dc
                r += sr
            if e2 < dr:
                err += dr
                c += sc

    def _in_exclusion_zone(self, row: int, col: int) -> bool:
        """Check if position is in the text exclusion zone."""
        return (
            self._text_row is not None
            and self._text_max_col is not None
            and row >= self._text_row
            and col <= self._text_max_col
        )

    def _place_pixel(
        self, pixels: dict[int, set[int]], row: int, col: int
    ) -> None:
        """Place a pixel if within display bounds and outside exclusion zone."""
        if 0 <= col < self._display_width and not self._in_exclusion_zone(
            row, col
        ):
            pixels[row].add(col)

    def render(self, canvas: np.ndarray) -> None:
        h, w = canvas.shape
        if self._state in (_LightningState.FLASH_OFF, _LightningState.IDLE):
            return  # bolt invisible during flash-off and idle

        # LEADER: show rows up to _leader_row; HOLDING: show all rows
        max_reveal = (
            int(self._leader_row)
            if self._state == _LightningState.LEADER
            else self._bolt_max_row
        )

        for row, cols in self._bolt.items():
            if row > max_reveal:
                continue
            for col in cols:
                if 0 <= row < h and 0 <= col < w:
                    canvas[row, col] = 1.0

    def configure(self, **params) -> None:
        if "strike_interval" in params:
            self._strike_interval = float(params["strike_interval"])
        if "leader_speed" in params:
            self._leader_speed = float(params["leader_speed"])

    def reset(self) -> None:
        self._state = _LightningState.IDLE
        self._timer = 0.0
        self._bolt = {}
        self._bolt_max_row = self._max_y
        self._leader_row = 0.0
        self._first_strike = True
