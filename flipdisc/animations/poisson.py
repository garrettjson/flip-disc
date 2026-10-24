"""Pressure solve for `fluid`: a 5-point Poisson system on a masked grid.

The unknowns are the cells where `mask` is set. Each couples to its four
neighbours with weight -1 when they are unknowns too and not at all otherwise,
so the caller decides through `diag` how walls and air count.

Small systems are solved exactly by banded Cholesky, whose cost grows with
cells × row length²: the fourth power of the size for a square grid, about
1 ms at 28×28 but 200 ms at 196×196. Larger ones use conjugate gradients
preconditioned by a multigrid V-cycle, whose cost grows with the number of
cells: about 9 ms at 196×196 (dev machine).

Each multigrid level merges 2×2 blocks of cells into one ("aggregation"). The
coarse operator is the exact Galerkin product, so every level is again a
5-point stencil and the V-cycle is symmetric positive definite, as CG needs.
Merging blocks interpolates the correction as a constant over each block,
which undershoots, so the correction is scaled up.
"""

import numpy as np
lazy from scipy.linalg import cho_solve_banded, cholesky_banded

# Systems with at most this many cells (in their bounding box) are solved
# directly; so is the coarsest multigrid level
_DIRECT_CELLS = 1024

# CG stops when the residual is this fraction of the right-hand side, which
# leaves the pressure within about 1e-4 of exact (relative to its peak)
_TOLERANCE = 1e-3
_MAX_ITERATIONS = 50

# Weight of the Jacobi sweep before and after each coarse correction
_JACOBI_WEIGHT = 0.8

# Scales each coarse correction; halves the CG iterations at 196×196
_OVERCORRECTION = 1.8


def solve(mask: np.ndarray, diag: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    """Return p, zero off `mask`, with (diag·p - Σ neighbours' p) = rhs on it."""
    out = np.zeros(mask.shape)
    rows = np.flatnonzero(mask.any(axis=1))
    if len(rows) == 0:
        return out
    cols = np.flatnonzero(mask.any(axis=0))

    # Only the bounding box of the unknowns takes part. Cells off the mask get
    # an identity row, so they solve to zero.
    box = np.s_[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    mask = mask[box]
    diag = np.where(mask, diag[box], 1.0)
    rhs = np.where(mask, rhs[box], 0.0)
    east = np.zeros(mask.shape)
    east[:, :-1] = np.where(mask[:, :-1] & mask[:, 1:], -1.0, 0.0)
    south = np.zeros(mask.shape)
    south[:-1] = np.where(mask[:-1] & mask[1:], -1.0, 0.0)

    if mask.size <= _DIRECT_CELLS:
        out[box] = _Banded(diag, east, south).solve(rhs.ravel()).reshape(mask.shape)
        return out

    multigrid = _Multigrid(diag, east, south, mask)
    padded = np.zeros(multigrid.shape)
    padded[: mask.shape[0], : mask.shape[1]] = rhs
    solved = multigrid.cg(padded.ravel()).reshape(multigrid.shape)
    out[box] = solved[: mask.shape[0], : mask.shape[1]]
    return out


def _pad_even(a: np.ndarray, fill: float | bool) -> np.ndarray:
    h, w = a.shape
    return np.pad(a, ((0, h % 2), (0, w % 2)), constant_values=fill)


def _coarsen(diag, east, south, mask) -> tuple:
    """Merge each 2×2 block (of an even-sized grid) into one cell."""
    d = np.where(mask, diag, 0.0)
    within = east[0::2, 0::2] + east[1::2, 0::2] + south[0::2, 0::2] + south[0::2, 1::2]
    coarse_diag = d[0::2, 0::2] + d[1::2, 0::2] + d[0::2, 1::2] + d[1::2, 1::2]
    coarse_diag += 2.0 * within
    coarse_east = east[0::2, 1::2] + east[1::2, 1::2]
    coarse_south = south[1::2, 0::2] + south[1::2, 1::2]
    coarse_mask = (
        mask[0::2, 0::2] | mask[1::2, 0::2] | mask[0::2, 1::2] | mask[1::2, 1::2]
    )
    coarse_diag = np.where(coarse_mask, coarse_diag, 1.0)
    return coarse_diag, coarse_east, coarse_south, coarse_mask


class _Banded:
    """Exact solve by banded Cholesky. `east` and `south` couple each cell to
    its neighbours (zero in the last column and row)."""

    def __init__(self, diag: np.ndarray, east: np.ndarray, south: np.ndarray):
        # The band is one row long, so run the rows along the shorter side
        self._transposed = diag.shape[1] > diag.shape[0]
        if self._transposed:
            diag, east, south = diag.T, south.T, east.T
        self._shape = diag.shape
        w = diag.shape[1]
        bands = np.zeros((w + 1, diag.size))
        bands[0] = diag.ravel()
        bands[1] = east.ravel()
        bands[w] = south.ravel()  # same row as east when w == 1, where east is 0
        self._factor = cholesky_banded(bands, lower=True, check_finite=False)

    def solve(self, b: np.ndarray) -> np.ndarray:
        if self._transposed:
            b = b.reshape(self._shape[::-1]).T.ravel()
        x = cho_solve_banded((self._factor, True), b, check_finite=False)
        if self._transposed:
            x = x.reshape(self._shape).T.ravel()
        return x


class _Level:
    """One even-sized multigrid level, stored flat so neighbours are
    contiguous slices."""

    def __init__(self, diag, east, south, mask, coarse_shape: tuple[int, int]):
        self.shape = diag.shape
        self._w = w = diag.shape[1]
        self._diag = diag.ravel()
        self._east = east.ravel()[:-1]
        self._south = south.ravel()[:-w]
        self._mask = mask.ravel().astype(np.float64)
        self._step = _JACOBI_WEIGHT / self._diag
        self._x = np.empty(diag.size)
        self._r = np.empty(diag.size)
        self._tmp = np.empty(diag.size)
        self._coarse_shape = coarse_shape
        self._coarse_rhs = np.zeros(coarse_shape)

    def apply(self, p: np.ndarray, out: np.ndarray) -> np.ndarray:
        w, tmp = self._w, self._tmp
        np.multiply(self._diag, p, out=out)
        np.multiply(self._east, p[1:], out=tmp[:-1])
        out[:-1] += tmp[:-1]
        np.multiply(self._east, p[:-1], out=tmp[:-1])
        out[1:] += tmp[:-1]
        np.multiply(self._south, p[w:], out=tmp[:-w])
        out[:-w] += tmp[:-w]
        np.multiply(self._south, p[:-w], out=tmp[:-w])
        out[w:] += tmp[:-w]
        return out

    def presmooth(self, b: np.ndarray) -> np.ndarray:
        """One Jacobi sweep from zero, into this level's buffer."""
        return np.multiply(self._step, b, out=self._x)

    def postsmooth(self, x: np.ndarray, b: np.ndarray) -> None:
        r = self.apply(x, self._r)
        np.subtract(b, r, out=r)
        r *= self._step
        x += r

    def restrict(self, x: np.ndarray, b: np.ndarray) -> np.ndarray:
        """The residual, summed over each 2×2 block."""
        r = self.apply(x, self._r)
        np.subtract(b, r, out=r)
        h, w = self.shape[0] // 2, self.shape[1] // 2
        pairs = (r[0::2] + r[1::2]).reshape(h, 2, w)  # columns, then rows
        np.add(pairs[:, 0], pairs[:, 1], out=self._coarse_rhs[:h, :w])
        self._coarse_rhs *= _OVERCORRECTION
        return self._coarse_rhs.ravel()

    def prolong(self, coarse: np.ndarray, x: np.ndarray) -> None:
        """Add the coarse correction to every unknown of each block."""
        h, w = self.shape[0] // 2, self.shape[1] // 2
        coarse = coarse.reshape(self._coarse_shape)[:h, :w]
        view = x.reshape(h, 2, 2 * w)
        view += np.repeat(coarse, 2, axis=1)[:, None, :]
        x *= self._mask


class _Multigrid:
    def __init__(self, diag, east, south, mask):
        grids = []
        while diag.size > _DIRECT_CELLS:
            diag, east, south = (
                _pad_even(diag, 1.0),
                _pad_even(east, 0.0),
                _pad_even(south, 0.0),
            )
            mask = _pad_even(mask, False)
            grids.append((diag, east, south, mask))
            diag, east, south, mask = _coarsen(diag, east, south, mask)
        self._coarsest = _Banded(diag, east, south)
        coarse_shapes = [grid[0].shape for grid in grids[1:]] + [diag.shape]
        self._levels = [
            _Level(*grid, shape)
            for grid, shape in zip(grids, coarse_shapes, strict=True)
        ]
        self.shape = self._levels[0].shape

    def _vcycle(self, k: int, b: np.ndarray) -> np.ndarray:
        if k == len(self._levels):
            return self._coarsest.solve(b)
        level = self._levels[k]
        x = level.presmooth(b)
        level.prolong(self._vcycle(k + 1, level.restrict(x, b)), x)
        level.postsmooth(x, b)
        return x

    def cg(self, b: np.ndarray) -> np.ndarray:
        """Preconditioned conjugate gradients from zero."""
        top = self._levels[0]
        x = np.zeros_like(b)
        r = b.copy()
        ad = np.empty_like(b)
        limit = _TOLERANCE * np.sqrt(b @ b)
        d = self._vcycle(0, r).copy()
        rz = r @ d
        for _ in range(_MAX_ITERATIONS):
            if np.sqrt(r @ r) <= limit:
                break
            top.apply(d, ad)
            alpha = rz / (d @ ad)
            x += alpha * d
            r -= alpha * ad
            z = self._vcycle(0, r)
            rz, previous = r @ z, rz
            d *= rz / previous
            d += z
        return x
