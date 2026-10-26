"""Tests for the black hole animation."""

import math

import numpy as np
import pytest

from flipdisc.animations.black_hole import BlackHole
from flipdisc.animations.viewport import Viewport
from flipdisc.exceptions import AnimationError


def _run(anim: BlackHole, seconds: float, dt: float = 0.05) -> None:
    for _ in range(round(seconds / dt)):
        anim.step(dt)


def test_render_shape_and_dtype():
    anim = BlackHole(Viewport(28, 28))
    _run(anim, 1.0)
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    assert set(np.unique(frame)) <= {0.0, 1.0}


def test_lights_a_readable_share_of_the_display():
    np.random.seed(0)
    anim = BlackHole(Viewport(28, 28))
    _run(anim, 5.0)
    assert 0.1 < anim.render_gray().mean() < 0.35


def test_shadow_hides_the_far_side():
    np.random.seed(0)
    anim = BlackHole(Viewport(28, 28))
    anim.configure(hole_size=0.4)
    shadow = int(0.4 * 14)
    upper = np.zeros((28, 28), dtype=bool)
    for _ in range(100):
        anim.step(0.05)
        upper |= anim.render_gray() > 0.5
    # A square inside the upper half of the shadow never lights
    assert not upper[14 - shadow + 1 : 13, 14 - shadow // 2 : 14 + shadow // 2].any()


def test_inner_orbits_are_faster():
    anim = BlackHole(Viewport(28, 28))
    assert anim._angular_speed(0.25) > anim._angular_speed(0.5) > anim._angular_speed(1)
    assert anim._angular_speed(0.5) == pytest.approx(anim.params["spin"])


def test_spin_turns_the_disc_counterclockwise():
    anim = BlackHole(Viewport(28, 28))
    anim.configure(inflow=0.0)
    before = anim._theta.copy()
    anim.step(0.05)
    turned = (anim._theta - before) % (2 * math.pi)
    assert (turned > 0).all() and (turned < math.pi).all()


def test_inflow_swallows_and_respawns_at_the_rim():
    anim = BlackHole(Viewport(28, 28))
    anim.configure(inflow=5.0)
    n = len(anim._r)
    _run(anim, 10.0)
    assert len(anim._r) == n
    assert anim._r.min() >= anim._inner_radius()
    assert anim._r.max() <= anim._rim


def test_density_scales_with_display_area():
    small = BlackHole(Viewport(28, 28))
    large = BlackHole(Viewport(56, 56))
    assert len(large._r) == pytest.approx(4 * len(small._r), rel=0.01)


def test_changing_density_keeps_existing_particles():
    anim = BlackHole(Viewport(28, 28))
    _run(anim, 1.0)
    anim.configure(density=0.1)
    kept = anim._r.copy()
    anim.configure(density=0.5)
    assert np.array_equal(anim._r[: len(kept)], kept)
    assert len(anim._r) == round(0.5 * 28 * 28)


def test_growing_the_hole_pushes_particles_out():
    anim = BlackHole(Viewport(28, 28))
    anim.configure(hole_size=0.6)
    assert anim._r.min() >= 0.6


@pytest.mark.parametrize(
    "params",
    [
        {"spin": -3.0, "trail": 6},
        {"hole_size": 0.0, "inflow": 5.0},
        {"tilt": 80, "arms": 6, "winding": 8.0},
        {"density": 2.0},
    ],
)
def test_extremes_render(params):
    anim = BlackHole(Viewport(28, 28))
    anim.configure(**params)
    _run(anim, 3.0)
    assert np.isfinite(anim._r).all() and np.isfinite(anim._theta).all()
    assert anim.render_gray().any()


def test_reset():
    anim = BlackHole(Viewport(28, 28))
    _run(anim, 2.0)
    anim.reset(seed=1)
    assert anim.current_time == 0.0
    assert anim._pattern_angle == 0.0


def test_unknown_param_is_rejected():
    with pytest.raises(AnimationError):
        BlackHole(Viewport(28, 28)).configure(radius=0.5)


@pytest.mark.parametrize(("w", "h"), [(14, 7), (28, 28), (56, 28), (40, 60)])
def test_different_sizes(w, h):
    anim = BlackHole(Viewport(w, h))
    _run(anim, 1.0)
    frame = anim.render_gray()
    assert frame.shape == (h, w)
    assert frame.any()
