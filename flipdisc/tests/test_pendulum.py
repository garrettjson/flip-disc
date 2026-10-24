"""Tests for the pendulum animation."""

import math

import numpy as np
import pytest

from flipdisc.animations.pendulum import Pendulum


def _period(anim: Pendulum, dt: float = 0.01) -> float:
    """Time between the first two swings through the bottom going the same way."""
    crossings = []
    previous = anim.angles[0]
    while len(crossings) < 2:
        anim.step(dt)
        if previous > 0 >= anim.angles[0]:
            crossings.append(anim.current_time)
        previous = anim.angles[0]
    return crossings[1] - crossings[0]


def _energy(anim: Pendulum) -> float:
    """Kinetic plus potential energy of the chain's unit masses, in px units."""
    arm = anim.length / len(anim.angles)
    sin, cos = np.sin(anim.angles), np.cos(anim.angles)
    depth = np.cumsum(arm * cos)
    vx = np.cumsum(arm * cos * anim.velocities)
    vy = np.cumsum(-arm * sin * anim.velocities)
    return float(0.5 * (vx**2 + vy**2).sum() - anim.gravity * depth.sum())


@pytest.mark.parametrize("arms", [1, 3, 5])
def test_render_shape_and_values(arms):
    anim = Pendulum(28, 28)
    anim.configure(arms=arms)
    for _ in range(100):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (28, 28)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}


def test_hangs_from_a_three_by_two_mount_at_the_top():
    anim = Pendulum(28, 28)
    anim.configure(initial_angle=0)
    frame = anim.render_gray()
    assert frame[0:2, 13:16].all()
    # Nothing else in the top two rows; the rod leaves the mount downwards
    assert frame[0:2].sum() == 6
    assert frame[2, 14]


def test_bob_is_about_three_dots_across():
    anim = Pendulum(28, 28)
    anim.configure(initial_angle=0)
    frame = anim.render_gray()
    bob_row = round(anim.anchor_y + anim.length)
    assert frame[bob_row].sum() == 3
    assert not frame[bob_row + 3 :].any()


def test_no_trail():
    swung = Pendulum(28, 28)
    for _ in range(37):
        swung.step(0.05)
    still = Pendulum(28, 28)
    still.angles = swung.angles
    # Only the pendulum's current position is drawn
    assert np.array_equal(swung.render_gray(), still.render_gray())


@pytest.mark.parametrize("arms", [1, 2, 5])
def test_lit_dots_follow_every_joint(arms):
    anim = Pendulum(28, 28)
    anim.configure(arms=arms)
    for _ in range(60):
        anim.step(0.05)
        frame = anim.render_gray()
        for x, y in anim._joint_positions():
            # Joints swung up over the pivot are off the top of the display
            if y < 0 or not 0 <= x < 28:
                continue
            # A joint on the edge of a pixel may light its neighbour instead
            row, column = int(y), int(x)
            assert frame[
                max(row - 1, 0) : row + 2, max(column - 1, 0) : column + 2
            ].any()


def test_arms_share_the_length():
    anim = Pendulum(28, 28)
    anim.configure(arms=4, initial_angle=0)
    joints = anim._joint_positions()
    assert len(joints) == 5
    assert joints[-1, 1] == pytest.approx(anim.length)
    assert np.diff(joints[:, 1]) == pytest.approx(np.full(4, anim.length / 4))


def test_length_is_a_fraction_of_the_display():
    anim = Pendulum(28, 28)
    anim.configure(length=0.5)
    assert anim.length == 14
    wide = Pendulum(56, 14)
    assert wide.length == pytest.approx(0.8 * 14)


@pytest.mark.parametrize(("width", "height"), [(28, 28), (56, 56), (28, 7)])
def test_swings_at_the_same_speed_on_any_display(width, height):
    # A small swing of the default 2 m pendulum takes 2π√(L/g) ≈ 2.8 s
    anim = Pendulum(width, height)
    anim.configure(initial_angle=0.1, damping=1.0)
    assert _period(anim) == pytest.approx(2 * math.pi * math.sqrt(2 / 9.81), rel=0.02)


@pytest.mark.parametrize("change", [{"initial_angle": -0.5}, {"arms": 3}])
def test_configure_restarts_from_rest(change):
    anim = Pendulum(28, 28)
    anim.configure(arms=2)
    for _ in range(10):
        anim.step(0.05)
    anim.configure(**change)
    arms, angle = anim.params["arms"], anim.params["initial_angle"]
    assert np.array_equal(anim.angles, np.full(arms, angle))
    assert not anim.velocities.any()


def test_changing_length_keeps_swinging():
    anim = Pendulum(28, 28)
    anim.configure(arms=2)
    for _ in range(10):
        anim.step(0.05)
    angles = anim.angles.copy()
    anim.configure(length=0.3)
    assert np.array_equal(anim.angles, angles)
    assert anim.velocities.any()


@pytest.mark.parametrize("arms", [2, 3, 5])
def test_chain_conserves_energy_without_damping(arms):
    anim = Pendulum(28, 28)
    anim.configure(arms=arms, damping=1.0, initial_angle=2.5)
    start = _energy(anim)
    for _ in range(600):
        anim.step(0.05)
    # Relative to the chain's potential energy span, m·g·L per mass
    assert abs(_energy(anim) - start) < 0.01 * anim.gravity * anim.length * arms


@pytest.mark.parametrize(("arms", "chaotic"), [(1, False), (2, True), (5, True)])
def test_multiple_arms_are_chaotic(arms, chaotic):
    def run(nudge: float) -> np.ndarray:
        anim = Pendulum(28, 28)
        anim.configure(arms=arms)  # default start, horizontal
        anim.angles[-1] += nudge
        for _ in range(600):
            anim.step(0.05)
        return anim.angles

    # A millionth of a radian grows to a different motion entirely
    apart = np.abs(run(0) - run(1e-6)).max()
    assert (apart > 0.5) == chaotic


@pytest.mark.parametrize(("width", "height"), [(7, 7), (14, 7), (28, 7), (1, 1)])
@pytest.mark.parametrize("arms", [1, 5])
def test_other_sizes(width, height, arms):
    anim = Pendulum(width, height)
    anim.configure(arms=arms)
    for _ in range(100):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (height, width)
        assert frame.any()
