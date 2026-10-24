"""3D simplex noise, computed for a whole grid at once with NumPy.

Stefan Gustavson's reference algorithm ("Simplex noise demystified", 2005),
with the branch-free choice of simplex used by GPU implementations so every
point is handled by the same array operations.
"""

import numpy as np

# Skew and unskew factors between the input space and the simplex grid
_F3 = 1.0 / 3.0
_G3 = 1.0 / 6.0

# Gradients: the midpoints of a cube's edges
_GRAD3 = np.array(
    [
        [1, 1, 0],
        [-1, 1, 0],
        [1, -1, 0],
        [-1, -1, 0],
        [1, 0, 1],
        [-1, 0, 1],
        [1, 0, -1],
        [-1, 0, -1],
        [0, 1, 1],
        [0, -1, 1],
        [0, 1, -1],
        [0, -1, -1],
    ],
    dtype=np.float64,
)


def permutation(seed: int = 0) -> np.ndarray:
    """The lattice hash for one noise field; each seed gives a different field."""
    p = np.random.default_rng(seed).permutation(256)
    # Doubled so a sum of a few lookups never needs wrapping
    return np.concatenate([p, p])


def simplex3(x: np.ndarray, y: np.ndarray, z: float, perm: np.ndarray) -> np.ndarray:
    """Noise at each (x, y) for one z, in about [-1, 1].

    ``x`` and ``y`` broadcast against each other, so a row of x and a column of
    y give a full grid. The extremes overshoot 1 slightly; clip if that matters.
    With Gustavson's kernel radius of 0.6, values can jump by up to about 0.003
    where two simplices meet, which binarizing hides.
    """
    x, y = np.broadcast_arrays(np.asarray(x, dtype=np.float64), y)
    z = np.full(x.shape, z, dtype=np.float64)

    # Which skewed unit cube the point is in, and its offset from the origin
    s = (x + y + z) * _F3
    i, j, k = np.floor(x + s), np.floor(y + s), np.floor(z + s)
    t = (i + j + k) * _G3
    x0, y0, z0 = x - i + t, y - j + t, z - k + t

    # Which of the cube's six tetrahedra: offsets of its second and third corners
    gx, gy, gz = x0 >= y0, y0 >= z0, z0 >= x0
    i1, j1, k1 = gx & ~gz, gy & ~gx, gz & ~gy
    i2, j2, k2 = gx | ~gz, gy | ~gx, gz | ~gy

    ii = i.astype(np.int64) & 255
    jj = j.astype(np.int64) & 255
    kk = k.astype(np.int64) & 255

    total = np.zeros(x.shape)
    for di, dj, dk, unskew in (
        (0, 0, 0, 0.0),
        (i1, j1, k1, _G3),
        (i2, j2, k2, 2 * _G3),
        (1, 1, 1, 3 * _G3),
    ):
        cx, cy, cz = x0 - di + unskew, y0 - dj + unskew, z0 - dk + unskew
        grad = _GRAD3[perm[ii + di + perm[jj + dj + perm[kk + dk]]] % 12]
        falloff = np.maximum(0.6 - cx * cx - cy * cy - cz * cz, 0.0)
        total += falloff**4 * (
            grad[..., 0] * cx + grad[..., 1] * cy + grad[..., 2] * cz
        )
    return 32.0 * total
