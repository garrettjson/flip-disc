"""Tests for the FLIP fluid simulation animation."""

from itertools import pairwise

import numpy as np
import pytest

from flipdisc.animations.fluid import FluidSimulation
from flipdisc.animations.viewport import Viewport
from flipdisc.exceptions import AnimationError


def _run(anim: FluidSimulation, frames: int, dt: float = 0.05) -> list[np.ndarray]:
    out = []
    for _ in range(frames):
        anim.step(dt)
        out.append(anim.render_gray() > 0.5)
    return out


def test_instantiation():
    anim = FluidSimulation(Viewport(28, 28))
    assert anim.width == 28
    assert anim.height == 28
    assert len(anim._x) > 0


def test_render_shape_and_dtype():
    anim = FluidSimulation(Viewport(28, 28))
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    assert frame.min() >= 0.0
    assert frame.max() <= 1.0


def test_starts_as_a_filled_block():
    frame = FluidSimulation(Viewport(28, 28)).render_gray() > 0.5
    assert not frame[:12].any()
    assert frame[16:].all()


def test_step_produces_finite_output():
    anim = FluidSimulation(Viewport(28, 28))
    for _ in range(40):
        anim.step(0.05)
        frame = anim.render_gray()
        assert np.isfinite(frame).all()
        assert set(np.unique(frame)) <= {0.0, 1.0}
    assert np.isfinite(anim._x).all() and np.isfinite(anim._vx).all()


def test_particles_stay_inside_the_tank():
    anim = FluidSimulation(Viewport(28, 28))
    anim.configure(slosh_amplitude=1.5, slosh_frequency=0.5)
    _run(anim, 100)
    r = anim._particle_radius
    assert anim._x.min() >= 1 + r - 1e-9 and anim._x.max() <= 29 - r + 1e-9
    assert anim._y.min() >= 1 + r - 1e-9 and anim._y.max() <= 29 - r + 1e-9


def test_keeps_its_volume_while_sloshing():
    np.random.seed(0)
    anim = FluidSimulation(Viewport(28, 28))
    lit = [f.sum() for f in _run(anim, 300)]
    nominal = 28 * 28 * 0.5
    assert min(lit) > 0.85 * nominal
    assert max(lit) < 1.1 * nominal


def test_settles_without_flipping_dots():
    np.random.seed(0)
    anim = FluidSimulation(Viewport(28, 28))
    anim.configure(slosh_amplitude=0.0)
    frames = _run(anim, 300)[200:]
    flips = sum((a != b).sum() for a, b in pairwise(frames))
    assert flips / len(frames) < 0.5
    # A flat surface: full rows below, nothing above
    assert frames[-1][16:].all()
    assert not frames[-1][:12].any()


def test_fluid_follows_gravity_direction():
    # Hold the tank tilted so gravity pulls towards the right wall
    frame = _tilted(FluidSimulation(Viewport(28, 28)), angle=0.6, frames=200)
    assert frame[:, 14:].sum() > frame[:, :14].sum() + 40


def _tilted(anim: FluidSimulation, angle: float, frames: int) -> np.ndarray:
    gx = anim._gravity * np.sin(angle)
    gy = anim._gravity * np.cos(angle)
    for _ in range(frames):
        anim._substep(0.025, gx, gy)
    return anim._density()[1:-1, 1:-1] > 0.5 * anim._rest_density


def test_configure_fill_level_restarts_with_more_fluid():
    anim = FluidSimulation(Viewport(28, 28))
    half = len(anim._x)
    anim.configure(fill_level=0.25)
    assert anim._fill_level == 0.25
    assert len(anim._x) < 0.6 * half


def test_full_tank_is_stable():
    anim = FluidSimulation(Viewport(28, 28))
    anim.configure(fill_level=1.0)
    frames = _run(anim, 20)
    assert np.isfinite(anim._vx).all()
    assert frames[-1].mean() > 0.9


def test_old_sph_params_are_rejected():
    anim = FluidSimulation(Viewport(28, 28))
    with pytest.raises(AnimationError):
        anim.configure(particle_count=100)


def test_reset():
    anim = FluidSimulation(Viewport(28, 28))
    count = len(anim._x)
    _run(anim, 10)
    anim.reset(seed=42)
    assert anim.current_time == 0.0
    assert len(anim._x) == count
    assert not anim._vx.any()


def test_different_sizes():
    for w, h in [(14, 7), (28, 28), (56, 28)]:
        anim = FluidSimulation(Viewport(w, h))
        _run(anim, 5)
        frame = anim.render_gray()
        assert frame.shape == (h, w)
