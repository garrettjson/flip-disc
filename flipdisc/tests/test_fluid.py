"""Tests for the SPH fluid simulation animation."""

import numpy as np

from flipdisc.animations.fluid import FluidSimulation


def test_instantiation():
    anim = FluidSimulation(28, 28)
    assert anim.width == 28
    assert anim.height == 28
    assert anim._particle_count == 150


def test_render_shape_and_dtype():
    anim = FluidSimulation(28, 28)
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    assert frame.min() >= 0.0
    assert frame.max() <= 1.0


def test_step_produces_finite_output():
    anim = FluidSimulation(28, 28)
    for _ in range(5):
        anim.step(1 / 60)
        frame = anim.render_gray()
        assert np.isfinite(frame).all()
        assert frame.min() >= 0.0
        assert frame.max() <= 1.0


def test_configure_particle_count():
    anim = FluidSimulation(28, 28)
    anim.configure(particle_count=100)
    assert anim._particle_count == 100
    assert len(anim._pos) == 100


def test_configure_fill_level():
    anim = FluidSimulation(28, 28)
    anim.configure(fill_level=0.3)
    assert anim._fill_level == 0.3


def test_reset():
    anim = FluidSimulation(28, 28)
    for _ in range(10):
        anim.step(1 / 60)
    anim.reset(seed=42)
    assert anim.current_time == 0.0
    assert len(anim._pos) == 150


def test_different_sizes():
    for w, h in [(14, 7), (28, 28), (56, 28)]:
        anim = FluidSimulation(w, h)
        anim.step(1 / 60)
        frame = anim.render_gray()
        assert frame.shape == (h, w)
