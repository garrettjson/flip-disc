"""Tests for the bouncing balls animation."""

import numpy as np
import pytest

from flipdisc.animations.bouncing_balls import BouncingBalls
from flipdisc.animations.viewport import Viewport


def _run(anim: BouncingBalls, frames: int, dt: float = 0.05) -> None:
    for _ in range(frames):
        anim.step(dt)


def _speeds(anim: BouncingBalls) -> np.ndarray:
    return np.hypot(anim._vel[:, 0], anim._vel[:, 1])


def _energy(anim: BouncingBalls) -> float:
    return float(0.5 * (_speeds(anim) ** 2).sum())


def _closest_approach(anim: BouncingBalls) -> float:
    """The smallest gap between any two balls' edges (negative if they overlap)."""
    apart = anim._pos[None, :, :] - anim._pos[:, None, :]
    gap = np.hypot(apart[..., 0], apart[..., 1]) - anim._diameter
    np.fill_diagonal(gap, np.inf)
    return float(gap.min())


@pytest.mark.parametrize("size", ["small", "large"])
def test_render_shape_and_values(size):
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(size=size)
    for _ in range(40):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (28, 28)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}


def test_balls_are_one_or_four_dots_across_on_a_28_dot_display():
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=1, size="small")
    assert anim.render_gray().sum() == 1
    anim.configure(size="large")
    frame = anim.render_gray()
    # A 4×4 square less its corners
    rows, cols = np.nonzero(frame)
    assert frame.sum() == 12
    assert np.ptp(rows) == 3 and np.ptp(cols) == 3


@pytest.mark.parametrize(
    ("width", "height", "small", "large"),
    # Balls grow more slowly than the display (scaling.py), never under a dot
    [(126, 126, 3, 12), (56, 56, 2, 7), (56, 28, 1, 4), (28, 7, 1, 1)],
)
def test_sizes_scale_with_the_display(width, height, small, large):
    anim = BouncingBalls(Viewport(width, height))
    anim.configure(size="small")
    assert anim._diameter == small
    anim.configure(size="large")
    assert anim._diameter == large


@pytest.mark.parametrize(("size", "count"), [("small", 60), ("large", 20)])
def test_starts_with_the_requested_balls_apart_at_the_requested_speed(size, count):
    np.random.seed(0)
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=count, size=size, speed=0.5)
    assert len(anim._pos) == count
    assert _closest_approach(anim) >= 0
    assert _speeds(anim) == pytest.approx(np.full(count, 0.5 * 28))


@pytest.mark.parametrize(("size", "count"), [("small", 60), ("large", 10)])
def test_conserves_energy_at_full_elasticity(size, count):
    np.random.seed(0)
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=count, size=size, speed=2)
    start = _energy(anim)
    _run(anim, 400)
    assert _energy(anim) == pytest.approx(start, rel=1e-9)


def test_collisions_spread_the_speeds_out():
    np.random.seed(0)
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=20, speed=1)
    _run(anim, 100)
    assert np.ptp(_speeds(anim)) > 0.5 * 28


@pytest.mark.parametrize(("size", "count"), [("small", 60), ("large", 20)])
def test_balls_never_pass_through_each_other_or_the_walls(size, count):
    np.random.seed(0)
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=count, size=size, speed=3)
    r = anim._radius
    for _ in range(200):
        anim.step(0.05)
        # Touching balls are pushed apart as soon as they meet, so they never
        # overlap by more than one substep's movement
        assert _closest_approach(anim) > -r
        assert (anim._pos >= r).all() and (anim._pos <= 28 - r).all()


def test_lower_elasticity_loses_energy():
    np.random.seed(0)
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(elasticity=0.8)
    start = _energy(anim)
    _run(anim, 400)
    assert _energy(anim) < 0.2 * start


def test_head_on_collision_swaps_velocities():
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=2, speed=0)
    anim._pos[:] = [(8.0, 14.0), (14.0, 14.0)]
    anim._vel[0] = (10.0, 0.0)
    _run(anim, 10)
    assert anim._vel[0] == pytest.approx((0.0, 0.0))
    assert anim._vel[1] == pytest.approx((10.0, 0.0))


def test_changing_speed_relaunches_the_balls_where_they_are():
    anim = BouncingBalls(Viewport(28, 28))
    _run(anim, 10)
    positions = anim._pos.copy()
    anim.configure(speed=1)
    assert np.array_equal(anim._pos, positions)
    assert _speeds(anim) == pytest.approx(np.full(len(positions), 28.0))


@pytest.mark.parametrize("change", [{"count": 4}, {"size": "small"}])
def test_changing_count_or_size_restarts(change):
    anim = BouncingBalls(Viewport(28, 28))
    _run(anim, 10)
    positions = anim._pos.copy()
    anim.configure(**change)
    assert len(anim._pos) == anim.params["count"]
    assert not np.array_equal(anim._pos[:4], positions[:4])
    assert _closest_approach(anim) >= 0


def test_no_balls_is_a_blank_display():
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=0)
    _run(anim, 5)
    assert not anim.render_gray().any()


def test_reset():
    anim = BouncingBalls(Viewport(28, 28))
    _run(anim, 10)
    anim.reset(seed=1)
    assert anim.current_time == 0.0
    assert len(anim._pos) == 10
    assert _closest_approach(anim) >= 0


@pytest.mark.parametrize(("width", "height"), [(1, 1), (7, 3), (28, 7), (56, 56)])
@pytest.mark.parametrize("size", ["small", "large"])
def test_other_sizes(width, height, size):
    anim = BouncingBalls(Viewport(width, height))
    anim.configure(size=size)
    for _ in range(50):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (height, width)
        assert frame.any()


def _hit_right_wall(size: int, squash: float) -> list[np.ndarray]:
    """Frames of one large ball hitting the right wall at full-squash speed."""
    anim = BouncingBalls(Viewport(size, size))
    anim.configure(count=1, speed=0, squash=squash)
    speed = 0.5 * size
    anim._pos[0] = (size - anim._radius - 0.1 * speed, size / 2)
    anim._vel[0] = (speed, 0.0)
    frames = []
    for _ in range(8):
        anim.step(0.05)
        frames.append(anim.render_gray())
    return frames


def test_a_hard_hit_flattens_the_ball_against_the_wall():
    frames = _hit_right_wall(56, squash=0.3)
    squashed = [
        (rows, cols)
        for rows, cols in map(np.nonzero, frames)
        if np.ptp(cols) < np.ptp(rows)
    ]
    assert squashed
    rows, cols = squashed[0]
    assert cols.max() == 55  # still touching the wall
    # Springs back to the same disc it was before the hit
    assert frames[-1].sum() == frames[0].sum()
    rows, cols = np.nonzero(frames[-1])
    assert np.ptp(cols) == np.ptp(rows) == 6  # a 7-dot ball at 56


def test_no_squash_keeps_every_ball_round():
    frames = _hit_right_wall(28, squash=0)
    assert all(frame.sum() == 12 for frame in frames)


def test_squash_is_only_drawn():
    def final_positions(squash: float) -> np.ndarray:
        np.random.seed(3)
        anim = BouncingBalls(Viewport(28, 28))
        anim.configure(count=20, squash=squash)
        _run(anim, 100)
        return anim._pos

    assert np.array_equal(final_positions(0), final_positions(0.5))


def test_colliding_balls_both_squash_towards_each_other():
    anim = BouncingBalls(Viewport(28, 28))
    anim.configure(count=2, speed=0)
    anim._pos[:] = [(8.0, 14.0), (14.0, 14.0)]
    anim._vel[0] = (20.0, 0.0)
    _run(anim, 4)  # meet in the fourth frame
    assert (anim._squash > 0).all()
    assert anim._squash_dir[0] == pytest.approx((1.0, 0.0))
    assert anim._squash_dir[1] == pytest.approx((-1.0, 0.0))
