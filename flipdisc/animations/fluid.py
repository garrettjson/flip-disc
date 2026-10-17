"""2D FLIP fluid simulation — liquid sloshing in a tank.

Particles carry the liquid; a grid with one cell per display pixel makes their
velocities incompressible. After Matthias Müller's "How to write a FLIP Water
Simulator" (Ten Minute Physics #18), vectorised in NumPy. Gravity direction
oscillates to drive sloshing.

Pipeline per substep:
  1. Apply gravity, move particles
  2. Push overlapping particles apart, collide with the walls
  3. Transfer particle velocities to the grid
  4. Solve for pressure so no fluid cell gains or loses volume, pushing
     outward where particles have bunched up ("drift compensation")
  5. Transfer the grid's velocity change back to the particles (FLIP),
     blended with the grid velocity itself (PIC)

The grid has a one-cell solid border, so cell (j, i) is display pixel
(j - 1, i - 1). Velocities are staggered: `u[j, i]` is the x-velocity on the
left face of cell (j, i), `v[j, i]` the y-velocity on its top face. y points
down.
"""

from __future__ import annotations

import math
from typing import Any, override

import numpy as np
from scipy.linalg import solveh_banded
from scipy.spatial import cKDTree

from .base import Animation, register_animation
from .params import Param

_TWO_PI = 2.0 * math.pi

# `substeps` is counted per this much simulated time
_SUBSTEP_REFERENCE = 1 / 20

# A dot turns on above ON and off below OFF (fractions of the packed particle
# density), so dots at the surface don't chatter between frames
_LIT_ON = 0.6
_LIT_OFF = 0.4

# Keeps the pressure system solvable when a body of fluid touches no air
_REGULARIZATION = 1e-6

# Push-apart finds neighbours once per substep and reuses them for both of its
# iterations (as the reference does), so it searches this much past the
# particle diameter to catch pairs the first iteration pushes together
_NEIGHBOR_SLACK = 0.2


@register_animation("fluid")
class FluidSimulation(Animation):
    """2D FLIP/PIC liquid with density-threshold rendering."""

    PARAMS = (
        # Changing fill_level or particle_radius restarts the simulation
        Param("fill_level", float, 0.5, min=0.05, max=1, step=0.05),
        Param("gravity", float, 40.0, min=0, max=500, step=5, unit="px/s²"),
        Param("slosh_amplitude", float, 0.25, min=0, max=3.14, step=0.05, unit="rad"),
        Param("slosh_frequency", float, 0.2, min=0, max=5, step=0.05, unit="Hz"),
        # 1 keeps every splash (noisy), 0 is thick and calm
        Param("flip_ratio", float, 0.7, min=0, max=1, step=0.05),
        # Fraction of sliding speed a particle loses per substep on a wall
        Param("wall_friction", float, 0.1, min=0, max=1, step=0.05),
        # Solver substeps per 1/20 s of simulated time
        Param("substeps", int, 2, min=1, max=8),
        # Smaller means more particles per pixel
        Param("particle_radius", float, 0.4, min=0.25, max=0.5, step=0.05, unit="px"),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))

        # Each parameter is mirrored in a private attribute of the same name
        for name, value in self.params.items():
            setattr(self, f"_{name}", value)

        self._init_grid()
        self._init_particles()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_grid(self) -> None:
        self._nx = nx = self.width + 2
        self._ny = ny = self.height + 2

        solid = np.ones((ny, nx), dtype=bool)
        solid[1:-1, 1:-1] = False
        self._solid = solid
        open_ = (~solid).astype(np.float64)
        self._open = open_

        # Faces that touch a solid cell carry no flow
        self._u_wall = solid | np.roll(solid, 1, axis=1)
        self._v_wall = solid | np.roll(solid, 1, axis=0)

        # Number of non-solid neighbours of each display cell
        self._open_neighbors = (
            open_[1:-1, :-2] + open_[1:-1, 2:] + open_[:-2, 1:-1] + open_[2:, 1:-1]
        )

        self._u = np.zeros((ny, nx))
        self._v = np.zeros((ny, nx))

    def _init_particles(self) -> None:
        """Hex-pack particles into the bottom fill_level fraction of the tank."""
        r = self._particle_radius
        dx = 2.0 * r
        dy = math.sqrt(3.0) / 2.0 * dx
        self._rest_density = 1.0 / (dx * dy)  # particles per cell when packed

        rows = max(1, round(self.height * self._fill_level / dy))
        cols = int(self.width / dx) + 1
        j, i = np.mgrid[0:rows, 0:cols]
        x = 1.0 + r + dx * i + np.where(j % 2 == 1, r, 0.0)
        y = self._ny - 1.0 - r - dy * j
        inside = (x <= self._nx - 1.0 - r) & (y >= 1.0 + r)

        # A little jitter so no two particles start exactly aligned
        n = int(inside.sum())
        self._x = x[inside] + np.random.uniform(-0.01, 0.01, n)
        self._y = y[inside] + np.random.uniform(-0.01, 0.01, n)
        self._vx = np.zeros(n)
        self._vy = np.zeros(n)
        self._collide()

        self._cell_density = self._density()
        self._lit = self._cell_density[1:-1, 1:-1] > 0.5 * self._rest_density

    # ------------------------------------------------------------------
    # Particle <-> grid transfer
    # ------------------------------------------------------------------

    def _stencil(self, offset_x: float, offset_y: float) -> tuple:
        """Bilinear weights onto a grid whose samples sit at (i + offset_x,
        j + offset_y). Returns (flat indices, weights), each of shape (4, n)."""
        px = self._x - offset_x
        py = self._y - offset_y
        i0 = np.floor(px).astype(np.intp)
        j0 = np.floor(py).astype(np.intp)
        tx = px - i0
        ty = py - j0
        base = j0 * self._nx + i0
        idx = np.stack([base, base + 1, base + self._nx, base + self._nx + 1])
        wts = np.stack([(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty])
        return idx, wts

    def _splat(self, idx: np.ndarray, wts: np.ndarray) -> np.ndarray:
        total = np.bincount(idx.ravel(), wts.ravel(), self._nx * self._ny)
        return total.reshape(self._ny, self._nx)

    def _density(self) -> np.ndarray:
        """Particles per cell, sampled at cell centres."""
        return self._splat(*self._stencil(0.5, 0.5))

    def _to_grid(self, idx: np.ndarray, wts: np.ndarray, vel: np.ndarray) -> np.ndarray:
        weight = self._splat(idx, wts)
        momentum = self._splat(idx, wts * vel)
        return np.divide(momentum, weight, out=np.zeros_like(weight), where=weight > 0)

    def _to_particles(
        self,
        idx: np.ndarray,
        wts: np.ndarray,
        field: np.ndarray,
        before: np.ndarray,
        valid: np.ndarray,
        vel: np.ndarray,
    ) -> None:
        # Faces between two air (or air and solid) cells hold no meaningful
        # velocity, so leave them out and renormalise
        wts = wts * valid.ravel()[idx]
        total = wts.sum(axis=0)
        usable = total > 0
        total = np.where(usable, total, 1.0)

        new = field.ravel()[idx]
        pic = (wts * new).sum(axis=0) / total
        flip = vel + (wts * (new - before.ravel()[idx])).sum(axis=0) / total
        blended = (1.0 - self._flip_ratio) * pic + self._flip_ratio * flip
        vel[usable] = blended[usable]

    # ------------------------------------------------------------------
    # Physics substep
    # ------------------------------------------------------------------

    def _push_apart(self) -> None:
        """Separate overlapping particles so the liquid keeps its volume."""
        min_dist = 2.0 * self._particle_radius
        n = len(self._x)

        # An unbalanced tree builds in half the time and queries no slower
        # at a few hundred particles
        pos = np.column_stack([self._x, self._y])
        tree = cKDTree(pos, balanced_tree=False, compact_nodes=False)
        pairs = tree.query_pairs(min_dist + _NEIGHBOR_SLACK, output_type="ndarray")
        if len(pairs) == 0:
            return
        a, b = pairs[:, 0], pairs[:, 1]

        for _ in range(2):
            dx = self._x[b] - self._x[a]
            dy = self._y[b] - self._y[a]
            dist = np.maximum(np.hypot(dx, dy), 1e-9)
            scale = np.maximum(0.5 * (min_dist - dist) / dist, 0.0)
            move_x = dx * scale
            move_y = dy * scale
            self._x += np.bincount(b, move_x, n) - np.bincount(a, move_x, n)
            self._y += np.bincount(b, move_y, n) - np.bincount(a, move_y, n)

    def _collide(self) -> None:
        """Keep particles inside the tank; walls stop them and rub."""
        r = self._particle_radius
        keep = 1.0 - self._wall_friction
        low = 1.0 + r

        high = self._nx - 1.0 - r
        hit = (self._x < low) | (self._x > high)
        self._vx[hit] = 0.0
        self._vy[hit] *= keep
        np.clip(self._x, low, high, out=self._x)

        high = self._ny - 1.0 - r
        hit = (self._y < low) | (self._y > high)
        self._vy[hit] = 0.0
        self._vx[hit] *= keep
        np.clip(self._y, low, high, out=self._y)

    def _project(self, fluid: np.ndarray, density: np.ndarray) -> None:
        """Make the grid velocities incompressible in fluid cells.

        Solves the pressure equation exactly: the system is symmetric and
        banded (each cell couples to its four neighbours), with one unknown
        per display cell and an identity row for cells that hold no fluid.
        """
        u, v = self._u, self._v
        w, h = self.width, self.height
        inner = fluid[1:-1, 1:-1]

        divergence = u[1:-1, 2:] - u[1:-1, 1:-1] + v[2:, 1:-1] - v[1:-1, 1:-1]
        # Drift compensation: ask for outflow where particles are packed
        # tighter than they should be
        divergence -= np.maximum(density[1:-1, 1:-1] - self._rest_density, 0.0)

        bands = np.zeros((w + 1, w * h))
        bands[0] = np.where(inner, self._open_neighbors + _REGULARIZATION, 1.0).ravel()
        right = np.zeros((h, w))
        right[:, :-1] = -1.0 * (inner[:, :-1] & inner[:, 1:])
        bands[1] = right.ravel()
        below = np.zeros((h, w))
        below[:-1, :] = -1.0 * (inner[:-1, :] & inner[1:, :])
        bands[w] = below.ravel()
        rhs = np.where(inner, -divergence, 0.0).ravel()

        pressure = np.zeros_like(u)
        solved = solveh_banded(bands, rhs, lower=True, check_finite=False)
        pressure[1:-1, 1:-1] = solved.reshape(h, w)

        open_ = self._open
        u[:, 1:] += (pressure[:, :-1] - pressure[:, 1:]) * open_[:, :-1] * open_[:, 1:]
        v[1:, :] += (pressure[:-1, :] - pressure[1:, :]) * open_[:-1, :] * open_[1:, :]

    def _substep(self, dt: float, gx: float, gy: float) -> None:
        self._vx += gx * dt
        self._vy += gy * dt
        self._x += self._vx * dt
        self._y += self._vy * dt
        self._collide()
        self._push_apart()
        self._collide()

        # A cell is fluid if it holds at least one particle
        fluid = np.zeros(self._nx * self._ny, dtype=bool)
        cell = np.floor(self._y).astype(np.intp) * self._nx
        cell += np.floor(self._x).astype(np.intp)
        fluid[cell] = True
        fluid = fluid.reshape(self._ny, self._nx)

        u_idx, u_wts = self._stencil(0.0, 0.5)
        v_idx, v_wts = self._stencil(0.5, 0.0)
        self._u = self._to_grid(u_idx, u_wts, self._vx)
        self._v = self._to_grid(v_idx, v_wts, self._vy)
        self._u[self._u_wall] = 0.0
        self._v[self._v_wall] = 0.0
        u_before = self._u.copy()
        v_before = self._v.copy()

        # Particles don't move again this substep, so step() reuses this
        self._cell_density = self._density()
        self._project(fluid, self._cell_density)

        # Only faces of a fluid cell are usable. (The reference code also
        # accepts faces of solid cells, which keeps the liquid from settling.)
        u_valid = fluid | np.roll(fluid, 1, axis=1)
        v_valid = fluid | np.roll(fluid, 1, axis=0)
        self._to_particles(u_idx, u_wts, self._u, u_before, u_valid, self._vx)
        self._to_particles(v_idx, v_wts, self._v, v_before, v_valid, self._vy)

    # ------------------------------------------------------------------
    # Animation interface
    # ------------------------------------------------------------------

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt

        # Oscillating gravity direction for sloshing
        t = self.current_time
        freq = self._slosh_frequency
        angle = self._slosh_amplitude * (
            math.sin(_TWO_PI * freq * t)
            + 0.3 * math.sin(_TWO_PI * freq * math.sqrt(2) * t)
        )
        gx = self._gravity * math.sin(angle)
        gy = self._gravity * math.cos(angle)

        # `substeps` is per 1/20 s of simulated time, so the substep size (and
        # with it the stability of the solver) doesn't depend on the frame rate
        substeps = max(1, round(self._substeps * dt / _SUBSTEP_REFERENCE))
        for _ in range(substeps):
            self._substep(dt / substeps, gx, gy)

        relative = self._cell_density[1:-1, 1:-1] / self._rest_density
        self._lit = np.where(self._lit, relative > _LIT_OFF, relative > _LIT_ON)

    @override
    def render_gray(self) -> np.ndarray:
        return self._lit.astype(np.float32)

    @override
    def on_configure(self, **params: Any) -> None:
        for name, value in params.items():
            setattr(self, f"_{name}", value)

        # Changing how much fluid there is restarts the simulation
        if "fill_level" in params or "particle_radius" in params:
            self._init_particles()

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._u[:] = 0.0
        self._v[:] = 0.0
        self._init_particles()
