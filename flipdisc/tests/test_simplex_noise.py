"""Tests for the NumPy simplex noise and the simplex_noise animation."""

import numpy as np

from flipdisc.animations.simplex_noise import SimplexNoise
from flipdisc.gfx.noise import permutation, simplex3


def _sample(seed: int = 0, z: float = 0.37) -> np.ndarray:
    coords = np.linspace(-20, 20, 400)
    return simplex3(coords[None, :], coords[:, None], z, permutation(seed))


def test_row_and_column_broadcast_to_a_grid():
    noise = simplex3(np.arange(5)[None, :], np.arange(3)[:, None], 0.0, permutation())
    assert noise.shape == (3, 5)


def test_range_is_about_minus_one_to_one():
    noise = _sample()
    assert np.abs(noise).max() < 1.1
    assert noise.min() < -0.8
    assert noise.max() > 0.8


def test_smooth_between_nearby_points():
    noise = _sample()  # points 0.1 apart
    assert np.abs(np.diff(noise, axis=0)).max() < 0.7
    assert np.abs(np.diff(noise, axis=1)).max() < 0.7
    fine = simplex3(np.linspace(0, 3, 3001), 0.5, 0.25, permutation())
    assert np.abs(np.diff(fine)).max() < 0.02  # points 0.001 apart


def test_seed_picks_the_field():
    assert np.array_equal(_sample(seed=3), _sample(seed=3))
    assert not np.array_equal(_sample(seed=3), _sample(seed=4))


def _run(anim: SimplexNoise, frames: int, dt: float = 0.05) -> np.ndarray:
    out = []
    for _ in range(frames):
        anim.step(dt)
        out.append(anim.render_gray())
    return np.array(out)


def test_render_shape_dtype_and_range():
    frames = _run(SimplexNoise(28, 14), 50)
    assert frames.shape == (50, 14, 28)
    assert frames.dtype == np.float32
    assert frames.min() >= 0.0
    assert frames.max() <= 1.0


def test_default_look_matches_opensimplex():
    """Blob size and flip rate stay where opensimplex had them (see _FREQUENCY)."""
    lit = _run(SimplexNoise(28, 28), 400) > 0.5
    neighbors_agree = (
        (lit[:, :, 1:] == lit[:, :, :-1]).mean() + (lit[:, 1:] == lit[:, :-1]).mean()
    ) / 2
    flips_per_frame = (lit[1:] != lit[:-1]).sum(axis=(1, 2)).mean()
    # opensimplex measured 82.9% and 27.2 at scale 4, speed 1
    assert 0.80 < neighbors_agree < 0.86
    assert 23 < flips_per_frame < 32
    assert 0.4 < lit.mean() < 0.6


def test_reset_restarts_and_seed_changes_the_field():
    anim = SimplexNoise(28, 28)
    first = anim.render_gray()
    _run(anim, 10)
    anim.reset()
    assert np.array_equal(anim.render_gray(), first)
    anim.reset(seed=7)
    assert not np.array_equal(anim.render_gray(), first)


def test_configure_scale_and_speed():
    anim = SimplexNoise(28, 28)
    anim.configure(scale=10.0, speed=0.0)
    still = _run(anim, 5)
    assert all(np.array_equal(still[0], f) for f in still)
