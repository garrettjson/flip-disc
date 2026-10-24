"""Tests for the fluid's pressure solver."""

import numpy as np
import pytest
import scipy.sparse as sp
import scipy.sparse.linalg as spl

from flipdisc.animations import poisson


def _system(h: int, w: int, fill: float, seed: int) -> tuple:
    """A fluid-like system: a random mask, walls around the grid, air elsewhere."""
    rng = np.random.default_rng(seed)
    mask = rng.random((h, w)) < fill
    open_ = np.ones((h + 2, w + 2))
    open_[[0, -1], :] = 0
    open_[:, [0, -1]] = 0
    neighbors = open_[1:-1, :-2] + open_[1:-1, 2:] + open_[:-2, 1:-1] + open_[2:, 1:-1]
    return mask, neighbors + 1e-6, rng.standard_normal((h, w))


def _exact(mask: np.ndarray, diag: np.ndarray, rhs: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    n = int(mask.sum())
    index = np.full((h, w), -1)
    index[mask] = np.arange(n)
    rows, cols, vals = [np.arange(n)], [np.arange(n)], [diag[mask]]
    for a, b in ((np.s_[:, :-1], np.s_[:, 1:]), (np.s_[:-1], np.s_[1:])):
        both = mask[a] & mask[b]
        i, j = index[a][both], index[b][both]
        rows += [i, j]
        cols += [j, i]
        vals += [-np.ones(len(i))] * 2
    matrix = sp.csc_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n, n),
    )
    out = np.zeros((h, w))
    out[mask] = spl.spsolve(matrix, rhs[mask])
    return out


def test_empty_mask_gives_zero():
    mask, diag, rhs = _system(10, 10, 0.0, seed=0)
    assert not poisson.solve(mask, diag, rhs).any()


@pytest.mark.parametrize("shape", [(14, 28), (28, 14), (3, 200), (200, 3), (1, 30)])
def test_small_systems_are_exact(shape):
    mask, diag, rhs = _system(*shape, 0.8, seed=1)
    p = poisson.solve(mask, diag, rhs)
    np.testing.assert_allclose(p, _exact(mask, diag, rhs), atol=1e-9)


@pytest.mark.parametrize("shape", [(64, 64), (61, 47), (30, 150), (101, 13)])
def test_large_systems_match_exact(shape):
    mask, diag, rhs = _system(*shape, 0.9, seed=2)
    assert mask.size > poisson._DIRECT_CELLS
    p = poisson.solve(mask, diag, rhs)
    exact = _exact(mask, diag, rhs)
    assert np.abs(p - exact).max() < 1e-3 * np.abs(exact).max()
    assert not p[~mask].any()


def test_large_closed_tank_matches_exact():
    # No air anywhere: only the small diagonal term keeps it solvable
    mask, diag, _ = _system(48, 48, 1.0, seed=3)
    rhs = np.ones(mask.shape)
    exact = _exact(mask, diag, rhs)
    p = poisson.solve(mask, diag, rhs)
    assert np.abs(p - exact).max() < 1e-3 * np.abs(exact).max()
