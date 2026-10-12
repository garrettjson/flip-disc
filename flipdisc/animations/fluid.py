"""2D SPH fluid simulation — liquid sloshing in a tank.

Simulates a cross-section of liquid using Smoothed Particle Hydrodynamics
(based on Sebastian Lague's approach). Below the surface = lit pixels,
above = dark, with splash particles breaking free naturally. Gravity
direction oscillates to drive sloshing.

Physics pipeline per substep:
  1. Apply gravity → predict positions
  2. Build spatial hash on predicted positions
  3. Compute densities (Spiky² for density, Spiky³ for near-density)
  4. Compute pressure forces (symmetric, dual-pressure)
  5. Apply viscosity (Poly6-weighted velocity smoothing)
  6. Integrate positions
  7. Enforce boundaries
"""

from __future__ import annotations

import math
from typing import Any, ClassVar, override

import numpy as np

from .base import Animation, register_animation

# ---------------------------------------------------------------------------
# SPH kernel constants (2D)
# ---------------------------------------------------------------------------

# Precomputed normalization constants, set per smoothing radius in _init_kernels
_TWO_PI = 2.0 * math.pi


def _make_render_stamp(radius: int) -> np.ndarray:
    """Precompute a circular splat stamp for rendering."""
    y, x = np.mgrid[-radius : radius + 1, -radius : radius + 1]
    dist_sq = x * x + y * y
    r_sq = (radius + 0.5) ** 2
    return np.clip(1.0 - dist_sq / r_sq, 0.0, 1.0).astype(np.float32)


@register_animation("fluid")
class FluidSimulation(Animation):
    """2D SPH fluid simulation with dual-pressure incompressibility and
    density-scatter rendering."""

    _DEFAULTS: ClassVar[dict[str, Any]] = {
        "particle_count": 150,
        "smoothing_radius": 3.5,
        "target_density": 0.4,
        "pressure_multiplier": 12000.0,
        "near_pressure_multiplier": 600.0,
        "viscosity_strength": 0.06,
        "gravity": 80.0,
        "collision_damping": 0.5,
        "substeps": 5,
        "time_scale": 1.0 / 3.0,
        "slosh_amplitude": 0.2,
        "slosh_frequency": 0.15,
        "fill_level": 0.5,
        "render_radius": 1,
        "density_threshold": 0.8,
    }

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))

        for k, v in self._DEFAULTS.items():
            setattr(self, f"_{k}", v)

        self._stamp = _make_render_stamp(self._render_radius)
        self._hash_size = 512
        self._init_kernels()
        self._init_particles()

    def _init_kernels(self) -> None:
        """Precompute kernel normalization constants for current smoothing radius."""
        h = self._smoothing_radius
        # Spiky pow2: (h - r)^2  — used for density
        self._k_spiky2 = 6.0 / (math.pi * h**4)
        # Spiky pow3: (h - r)^3  — used for near-density
        self._k_spiky3 = 10.0 / (math.pi * h**5)
        # Derivatives (for pressure gradient)
        self._k_spiky2_grad = -12.0 / (math.pi * h**4)
        self._k_spiky3_grad = -30.0 / (math.pi * h**5)
        # Poly6: (h^2 - r^2)^3  — used for viscosity
        self._k_poly6 = 4.0 / (math.pi * h**8)

    # ------------------------------------------------------------------
    # Particle initialization
    # ------------------------------------------------------------------

    def _init_particles(self) -> None:
        """Arrange particles in a jittered grid in the bottom fill_level fraction."""
        n = self._particle_count
        fill_h = self.height * self._fill_level

        aspect = self.width / fill_h if fill_h > 0 else 1.0
        cols = max(1, int(math.sqrt(n * aspect)))
        rows = max(1, math.ceil(n / cols))

        spacing_x = self.width / (cols + 1)
        spacing_y = fill_h / (rows + 1)

        positions = []
        for r in range(rows):
            for c in range(cols):
                if len(positions) >= n:
                    break
                x = (c + 1) * spacing_x
                y = self.height - fill_h + (r + 1) * spacing_y
                positions.append([x, y])

        while len(positions) < n:
            positions.append(
                [
                    np.random.uniform(0.5, self.width - 0.5),
                    np.random.uniform(self.height - fill_h, self.height - 0.5),
                ]
            )

        self._pos = np.array(positions[:n], dtype=np.float64)
        self._vel = np.zeros_like(self._pos)
        self._pos += np.random.uniform(-0.2, 0.2, self._pos.shape)

        # Preallocate per-particle density arrays
        self._density = np.zeros(n, dtype=np.float64)
        self._near_density = np.zeros(n, dtype=np.float64)

    # ------------------------------------------------------------------
    # Spatial hash
    # ------------------------------------------------------------------

    def _build_spatial_hash(self, pos: np.ndarray) -> None:
        """Build spatial hash for O(1) neighbor lookup."""
        h = self._smoothing_radius
        n = len(pos)

        cx = (pos[:, 0] / h).astype(np.int64)
        cy = (pos[:, 1] / h).astype(np.int64)
        self._cell_keys = (cx * 15823 + cy * 9737333) % self._hash_size
        self._sort_order = np.argsort(self._cell_keys)
        sorted_keys = self._cell_keys[self._sort_order]

        self._bucket_start = np.full(self._hash_size, n, dtype=np.int64)
        self._bucket_end = np.full(self._hash_size, n, dtype=np.int64)

        if n > 0:
            changes = np.where(np.diff(sorted_keys) != 0)[0] + 1
            starts = np.concatenate([[0], changes])
            ends = np.concatenate([changes, [n]])
            bucket_ids = sorted_keys[starts]
            self._bucket_start[bucket_ids] = starts
            self._bucket_end[bucket_ids] = ends

        self._cx = cx
        self._cy = cy

        # Precompute 9-cell hash keys for each particle (n, 9)
        offsets_x = np.array([-1, 0, 1, -1, 0, 1, -1, 0, 1], dtype=np.int64)
        offsets_y = np.array([-1, -1, -1, 0, 0, 0, 1, 1, 1], dtype=np.int64)
        cell_keys_9 = (
            (cx[:, None] + offsets_x) * 15823 + (cy[:, None] + offsets_y) * 9737333
        ) % self._hash_size
        self._cell_keys_9 = cell_keys_9

    def _get_neighbor_data(
        self, idx: int, pos: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Find neighbors of particle idx within smoothing radius.

        Returns (neighbor_indices, diff_vectors, distances) or None.
        """
        h_sq = self._smoothing_radius**2
        keys = self._cell_keys_9[idx]
        starts = self._bucket_start[keys]
        ends = self._bucket_end[keys]

        # Collect candidates from non-empty buckets
        candidates = []
        for k in range(9):
            if starts[k] < ends[k]:
                candidates.append(self._sort_order[starts[k] : ends[k]])

        if not candidates:
            return None
        cand = np.concatenate(candidates)

        diff = pos[cand] - pos[idx]
        dist_sq = diff[:, 0] ** 2 + diff[:, 1] ** 2
        mask = (dist_sq < h_sq) & (cand != idx)
        if not np.any(mask):
            return None

        neighbors = cand[mask]
        d = diff[mask]
        r = np.sqrt(dist_sq[mask])
        return neighbors, d, r

    # ------------------------------------------------------------------
    # Physics substep
    # ------------------------------------------------------------------

    def _substep(self, dt_sub: float) -> None:
        """SPH substep: gravity → predict → hash → density+pressure+viscosity → integrate → boundaries."""
        vel = self._vel

        # Oscillating gravity for sloshing
        t = self.current_time
        freq = self._slosh_frequency
        amp = self._slosh_amplitude
        angle = amp * (
            math.sin(_TWO_PI * freq * t)
            + 0.3 * math.sin(_TWO_PI * freq * math.sqrt(2) * t)
        )
        vel[:, 0] += self._gravity * math.sin(angle) * dt_sub
        vel[:, 1] += self._gravity * math.cos(angle) * dt_sub

        # Predict positions — fixed lookahead (matching Seb Lague) stabilizes
        # the spatial hash by keeping neighbor lookups consistent across timesteps
        predicted = self._pos + vel * (1.0 / 120.0)

        # Build spatial hash and cache all neighbor data once
        self._build_spatial_hash(predicted)
        neighbor_cache = self._cache_neighbors(predicted)

        # Pass 1: compute all densities (including wall mirror corrections)
        self._compute_densities(neighbor_cache, predicted)
        # Pass 2: pressure forces + viscosity (combined, reusing cached neighbors)
        self._apply_forces(neighbor_cache, dt_sub, predicted)

        # Integrate and enforce boundaries
        self._pos += vel * dt_sub
        self._enforce_boundaries()

    def _cache_neighbors(
        self, pos: np.ndarray
    ) -> list[tuple[np.ndarray, np.ndarray, np.ndarray] | None]:
        """Find and cache neighbors for all particles in one pass."""
        n = self._particle_count
        cache: list[tuple[np.ndarray, np.ndarray, np.ndarray] | None] = []

        for i in range(n):
            cache.append(self._get_neighbor_data(i, pos))
        return cache

    def _compute_densities(
        self,
        cache: list[tuple[np.ndarray, np.ndarray, np.ndarray] | None],
        predicted: np.ndarray,
    ) -> None:
        """Compute density and near-density for all particles using Spiky kernels."""
        h = self._smoothing_radius
        k2 = self._k_spiky2
        k3 = self._k_spiky3

        # Self-contribution: kernel evaluated at r=0 (particle's own density)
        self_density = k2 * h * h
        self_near_density = k3 * h * h * h

        # Precompute wall distances for mirror particle density correction.
        # Each particle near a wall gets density from its virtual reflection,
        # which provides the "wall pressure" missing from the truncated kernel.
        wall_dists = np.column_stack([
            predicted[:, 0],                  # left wall
            self.width - predicted[:, 0],     # right wall
            predicted[:, 1],                  # top wall
            self.height - predicted[:, 1],    # bottom wall
        ])
        half_h = h * 0.5
        # Mirror is at 2*d; only contributes if 2*d < h, i.e. d < h/2
        wall_mask = wall_dists < half_h
        mirror_dists = 2.0 * wall_dists
        mirror_diff = h - mirror_dists  # (h - 2d), positive where mask is True

        for i, entry in enumerate(cache):
            if entry is None:
                self._density[i] = self_density
                self._near_density[i] = self_near_density
            else:
                _neighbors, _d, r = entry
                diff = h - r
                self._density[i] = self_density + k2 * np.sum(diff * diff)
                self._near_density[i] = self_near_density + k3 * np.sum(diff * diff * diff)

            # Add mirror particle contributions for nearby walls
            for w in range(4):
                if wall_mask[i, w]:
                    md = mirror_diff[i, w]
                    self._density[i] += k2 * md * md
                    self._near_density[i] += k3 * md * md * md

    def _apply_forces(
        self,
        cache: list[tuple[np.ndarray, np.ndarray, np.ndarray] | None],
        dt_sub: float,
        predicted: np.ndarray,
    ) -> None:
        """Apply pressure forces and viscosity using cached neighbor data."""
        vel = self._vel
        h = self._smoothing_radius
        h_sq = h * h
        half_h = h * 0.5
        target = self._target_density
        p_mult = self._pressure_multiplier
        np_mult = self._near_pressure_multiplier
        k2g = self._k_spiky2_grad
        k3g = self._k_spiky3_grad
        k_poly6 = self._k_poly6
        visc = self._viscosity_strength

        # Wall normal directions: force pushes AWAY from each wall
        #   left (x=0): +x, right (x=W): -x, top (y=0): +y, bottom (y=H): -y
        wall_normals = [(1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)]

        for i, entry in enumerate(cache):
            density_i = max(self._density[i], 0.01)
            pressure_i = (self._density[i] - target) * p_mult
            near_pressure_i = self._near_density[i] * np_mult

            if entry is not None:
                neighbors, d, r = entry

                # --- Pressure from neighbors ---
                pressure_j = (self._density[neighbors] - target) * p_mult
                near_pressure_j = self._near_density[neighbors] * np_mult

                shared_pressure = (pressure_i + pressure_j) * 0.5
                shared_near = (near_pressure_i + near_pressure_j) * 0.5

                diff = h - r
                r_safe = np.maximum(r, 1e-8)
                dir_x = d[:, 0] / r_safe
                dir_y = d[:, 1] / r_safe

                grad2 = k2g * diff
                grad3 = k3g * diff * diff

                density_j = np.maximum(self._density[neighbors], 0.01)
                force_mag = (shared_pressure * grad2 + shared_near * grad3) / density_j

                vel[i, 0] += np.sum(force_mag * dir_x) * dt_sub / density_i
                vel[i, 1] += np.sum(force_mag * dir_y) * dt_sub / density_i

                # --- Viscosity ---
                diff_sq = h_sq - r * r
                w = k_poly6 * diff_sq * diff_sq * diff_sq
                vel[i, 0] += np.sum(w * (vel[neighbors, 0] - vel[i, 0])) * visc * dt_sub
                vel[i, 1] += np.sum(w * (vel[neighbors, 1] - vel[i, 1])) * visc * dt_sub

            # --- Wall mirror pressure ---
            # Mirror particle has same density/pressure as self; force pushes
            # away from wall (the reaction force the wall would exert).
            px, py = predicted[i]
            wall_dists = [px, self.width - px, py, self.height - py]
            for w_idx in range(4):
                wd = wall_dists[w_idx]
                if wd >= half_h:
                    continue
                mirror_r = 2.0 * wd
                md = h - mirror_r
                g2 = k2g * md
                g3 = k3g * md * md
                # Mirror has same pressure → shared = self pressure
                fm = (pressure_i * g2 + near_pressure_i * g3) / density_i
                nx, ny = wall_normals[w_idx]
                vel[i, 0] += fm * nx * dt_sub / density_i
                vel[i, 1] += fm * ny * dt_sub / density_i

    def _enforce_boundaries(self) -> None:
        """Clamp particles to tank walls with damped velocity reflection."""
        pos = self._pos
        vel = self._vel
        damp = self._collision_damping
        margin = 0.1

        mask = pos[:, 0] < margin
        pos[mask, 0] = margin
        vel[mask, 0] = abs(vel[mask, 0]) * damp

        mask = pos[:, 0] > self.width - margin
        pos[mask, 0] = self.width - margin
        vel[mask, 0] = -abs(vel[mask, 0]) * damp

        mask = pos[:, 1] < margin
        pos[mask, 1] = margin
        vel[mask, 1] = abs(vel[mask, 1]) * damp

        mask = pos[:, 1] > self.height - margin
        pos[mask, 1] = self.height - margin
        vel[mask, 1] = -abs(vel[mask, 1]) * damp

    # ------------------------------------------------------------------
    # Animation interface
    # ------------------------------------------------------------------

    @override
    def step(self, dt: float) -> None:
        # time_scale < 1 plays the simulation in slow motion
        dt *= self._time_scale
        self.current_time += dt

        # `substeps` is per 1/60 s of simulated time, so the substep size (and
        # with it the stability of the solver) doesn't depend on the frame rate
        substeps = max(1, round(self._substeps * dt * 60.0))
        dt_sub = dt / substeps
        for _ in range(substeps):
            self._substep(dt_sub)

    @override
    def render_gray(self) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        stamp = self._stamp
        r = self._render_radius
        sh, sw = stamp.shape

        # Vectorized scatter: for each offset in the stamp, accumulate
        # contributions from all particles at once using np.add.at
        px_all = np.rint(self._pos[:, 0]).astype(np.intp)
        py_all = np.rint(self._pos[:, 1]).astype(np.intp)

        for sy in range(sh):
            for sx in range(sw):
                weight = stamp[sy, sx]
                if weight == 0:
                    continue
                cy = py_all + sy - r
                cx = px_all + sx - r
                valid = (cy >= 0) & (cy < self.height) & (cx >= 0) & (cx < self.width)
                np.add.at(canvas, (cy[valid], cx[valid]), weight)

        if self._density_threshold > 0:
            canvas /= self._density_threshold
        np.clip(canvas, 0.0, 1.0, out=canvas)
        return canvas

    @override
    def configure(self, **params: Any) -> None:
        super().configure(**params)

        rebuild = False
        for key, default in self._DEFAULTS.items():
            if key in params:
                val = type(default)(params[key])
                setattr(self, f"_{key}", val)
                if key in ("particle_count", "fill_level"):
                    rebuild = True

        if "render_radius" in params:
            self._stamp = _make_render_stamp(self._render_radius)

        if "smoothing_radius" in params:
            self._init_kernels()

        if rebuild:
            self._init_particles()

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._init_particles()
