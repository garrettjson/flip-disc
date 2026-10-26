"""Tests for the spinning point cloud animation."""

import math

import numpy as np
import pytest

from flipdisc.animations.point_cloud import PointCloud
from flipdisc.animations.viewport import Viewport
from flipdisc.exceptions import AnimationError


def _settle(anim: PointCloud, seconds: float = 5.0, dt: float = 0.05) -> None:
    for _ in range(round(seconds / dt)):
        anim.step(dt)


def _radii(anim: PointCloud) -> np.ndarray:
    return np.linalg.norm(anim._pos, axis=1)


def test_render_shape_and_dtype():
    anim = PointCloud(Viewport(28, 28))
    _settle(anim, 1.0)
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    assert set(np.unique(frame)) <= {0.0, 1.0}


def test_starts_at_the_centre_and_bursts_out():
    anim = PointCloud(Viewport(28, 28))
    assert not anim._pos.any()
    assert anim.render_gray().sum() == 1
    _settle(anim, 0.3)
    assert anim.render_gray().sum() > 50


def test_settles_onto_the_shell():
    np.random.seed(0)
    anim = PointCloud(Viewport(28, 28))
    _settle(anim)
    r = _radii(anim)
    inner = 1.0 - anim.params["thickness"]
    assert r.min() > inner - 0.02
    assert r.max() < 1.02


def test_spins_at_the_requested_speed():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(spin_speed=0.5)
    _settle(anim, 10.0)
    assert anim._spin_rate == pytest.approx(0.5, rel=1e-2)
    # Riding along with the anchors, so moving at the body's speed
    speed = np.linalg.norm(anim._vel[:, [0, 2]], axis=1)
    horizontal = np.linalg.norm(anim._pos[:, [0, 2]], axis=1)
    assert speed == pytest.approx(0.5 * horizontal, abs=1e-2)


def test_spin_up_is_gradual():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(spin_speed=2.0)
    anim.step(0.05)
    assert 0 < anim._spin_rate < 0.2


def test_fast_spin_bulges_the_equator():
    np.random.seed(0)
    anim = PointCloud(Viewport(28, 28))
    anim.configure(spin_speed=3.0, thickness=0.0)
    _settle(anim, 10.0)
    equator = np.linalg.norm(anim._pos[:, [0, 2]], axis=1).max()
    pole = np.abs(anim._pos[:, 1]).max()
    assert equator > 1.1
    assert pole < 1.01


def _heights(concentration: float, at: str) -> np.ndarray:
    np.random.seed(0)
    anim = PointCloud(Viewport(28, 28))
    anim.configure(
        count=2000, concentration=concentration, concentrate_at=at, thickness=0.0
    )
    return np.abs(anim._anchors[:, 1])


@pytest.mark.parametrize("at", ["poles", "equator"])
def test_no_concentration_is_even_either_way(at):
    # The caps above 0.9 and the band below 0.1 are each 10% of the surface
    heights = _heights(0.0, at)
    assert (heights > 0.9).mean() == pytest.approx(0.1, abs=0.03)
    assert (heights < 0.1).mean() == pytest.approx(0.1, abs=0.03)


def test_concentration_crowds_the_poles():
    # Latitude-uniform: 1 - asin(0.9) / (pi / 2)
    cap = math.asin(0.9) / (math.pi / 2)
    assert (_heights(1.0, "poles") > 0.9).mean() == pytest.approx(1 - cap, abs=0.03)
    # Twice latitude-uniform's excess over area-uniform
    assert (_heights(2.0, "poles") > 0.9).mean() == pytest.approx(1 - cap**2, abs=0.03)


def test_concentration_crowds_the_equator():
    for concentration in (1.0, 2.0, 3.0):
        share = (_heights(concentration, "equator") < 0.1).mean()
        assert share == pytest.approx(0.1 ** (1 / (1 + concentration)), abs=0.03)
    assert (_heights(2.0, "equator") > 0.9).mean() < 0.05


def test_pole_concentration_is_continuous_at_one():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(concentration=1.0)
    at_one = anim._anchors.copy()
    anim.configure(concentration=1.0001)
    assert np.allclose(anim._anchors, at_one, atol=1e-3)


def test_switching_direction_keeps_each_dot_in_its_hemisphere():
    anim = PointCloud(Viewport(28, 28))
    poles = anim._anchors.copy()
    anim.configure(concentrate_at="equator")
    # Dots slide along their meridians: same longitude, same side of the
    # equator
    assert np.array_equal(np.sign(anim._anchors[:, 1]), np.sign(poles[:, 1]))
    assert np.allclose(
        np.arctan2(anim._anchors[:, 2], anim._anchors[:, 0]),
        np.arctan2(poles[:, 2], poles[:, 0]),
    )


def test_thickness_fills_the_ball():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(thickness=1.0, count=1000)
    r = np.linalg.norm(anim._anchors, axis=1)
    assert r.min() < 0.3
    assert r.max() <= 1.0


def test_count_scales_with_display_area():
    small = PointCloud(Viewport(28, 28))
    large = PointCloud(Viewport(56, 56))
    assert len(large._pos) == pytest.approx(4 * len(small._pos), rel=0.01)


def test_count_overrides_density():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(count=40)
    assert len(anim._pos) == 40
    anim.configure(density=2.0)
    assert len(anim._pos) == 40


def test_changing_count_keeps_existing_dots():
    anim = PointCloud(Viewport(28, 28))
    _settle(anim, 2.0)
    before = anim._pos[:50].copy()
    anim.configure(count=50)
    assert np.array_equal(anim._pos, before)
    anim.configure(count=80)
    assert np.array_equal(anim._pos[:50], before)
    assert not anim._pos[50:].any()


def test_changing_shape_moves_anchors_not_dots():
    anim = PointCloud(Viewport(28, 28))
    _settle(anim, 2.0)
    pos = anim._pos.copy()
    anchors = anim._anchors.copy()
    anim.configure(concentration=0.0)
    assert np.array_equal(anim._pos, pos)
    assert not np.array_equal(anim._anchors, anchors)


def test_jitter_wanders_around_the_shell():
    np.random.seed(0)
    anim = PointCloud(Viewport(28, 28))
    anim.configure(jitter=1.0, thickness=0.0)
    _settle(anim, 10.0)
    offset_px = (_radii(anim) - 1.0) * anim._radius_px()
    # Radial RMS settles near the requested 1 px
    assert np.sqrt(np.mean(offset_px**2)) == pytest.approx(1.0, rel=0.3)


@pytest.mark.parametrize(
    "params",
    [
        {"spin_speed": 3.0, "thickness": 1.0},
        {"spin_speed": -3.0, "tilt": 90},
        {"jitter": 2.0, "count": 5000},
    ],
)
def test_extremes_stay_finite(params):
    anim = PointCloud(Viewport(28, 28))
    anim.configure(**params)
    _settle(anim, 5.0, dt=0.1)
    assert np.isfinite(anim._pos).all()
    assert _radii(anim).max() < 2.0


def _top_pole(anim: PointCloud) -> np.ndarray:
    """Where the body's top pole (-y) points in the world."""
    anim._anchors = np.array([[0.0, -1.0, 0.0]])
    return anim._anchor_state()[0][0]


def test_tilt_brings_the_top_pole_forward():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(tilt=30)
    assert _top_pole(anim)[2] == pytest.approx(math.sin(math.radians(30)))


def test_wobble_circles_the_axis_around_its_tilt():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(tilt=20, wobble=15, wobble_speed=1.0)
    base = _rot_x_world(20) @ np.array([0.0, -1.0, 0.0])
    poles = []
    for _ in range(63):  # just over one wobble period
        anim._substep(0.1)
        pole = _top_pole(anim)
        assert math.degrees(math.acos(pole @ base)) == pytest.approx(15, abs=1e-6)
        poles.append(pole)
    # It leans every way in turn: the poles' mean sits on the base axis
    mean = np.mean(poles, axis=0)
    assert mean / np.linalg.norm(mean) == pytest.approx(base, abs=0.02)


def _rot_x_world(tilt_deg: float) -> np.ndarray:
    t = math.radians(tilt_deg)
    return np.array(
        [[1, 0, 0], [0, math.cos(t), math.sin(t)], [0, -math.sin(t), math.cos(t)]]
    )


def test_no_wobble_means_wobble_speed_does_nothing():
    a, b = PointCloud(Viewport(28, 28)), PointCloud(Viewport(28, 28))
    b._uniforms = a._uniforms.copy()
    b._place_anchors()
    b.configure(wobble_speed=2.5)
    _settle(a, 2.0)
    _settle(b, 2.0)
    assert np.allclose(a._pos, b._pos)


def test_anchor_velocity_matches_their_motion():
    # The closed-form angular velocity agrees with differencing positions
    anim = PointCloud(Viewport(28, 28))
    anim.configure(tilt=25, wobble=20, wobble_speed=-1.3, spin_speed=2.0)
    _settle(anim, 5.0)
    h = 1e-6
    before, vel = anim._anchor_state()
    anim._spin_angle += anim._spin_rate * h
    anim._wobble_angle += anim.params["wobble_speed"] * h
    after, _ = anim._anchor_state()
    assert vel == pytest.approx((after - before) / h, abs=1e-4)


def test_steady_spin_rides_with_the_anchors():
    np.random.seed(0)
    anim = PointCloud(Viewport(28, 28))
    anim.configure(spin_speed=2.0, thickness=0.0)
    _settle(anim, 10.0)
    anchors, _ = anim._anchor_state()
    offset = anim._pos - anchors
    horizontal = anchors * [1, 0, 1]
    from_axis = np.linalg.norm(horizontal, axis=1)
    outward = horizontal / from_axis[:, None]
    along = np.cross([0.0, 1.0, 0.0], outward)

    # Pushed out from the axis by spin² / (k - spin²) of the anchor's
    # distance from it (the integrator lands within ~10%)...
    bulge = np.einsum("ij,ij->i", offset, outward) / from_axis
    assert bulge.mean() == pytest.approx(4.0 / (60.0 - 4.0), rel=0.15)
    # ...without trailing behind (damping against the spin trails ~0.14)
    assert np.abs(np.einsum("ij,ij->i", offset, along)).max() < 0.03
    assert np.abs(offset[:, 1]).max() < 1e-6


def test_reset():
    anim = PointCloud(Viewport(28, 28))
    anim.configure(spin_speed=1.0)
    _settle(anim, 2.0)
    anim.reset(seed=42)
    assert anim.current_time == 0.0
    assert anim._spin_rate == 0.0
    assert not anim._pos.any() and not anim._vel.any()


def test_unknown_param_is_rejected():
    with pytest.raises(AnimationError):
        PointCloud(Viewport(28, 28)).configure(radius=0.5)


@pytest.mark.parametrize(("w", "h"), [(14, 7), (28, 28), (56, 28), (40, 60)])
def test_different_sizes(w, h):
    anim = PointCloud(Viewport(w, h))
    _settle(anim, 1.0)
    frame = anim.render_gray()
    assert frame.shape == (h, w)
    assert frame.any()
