"""Tests for the bouncing dot animation."""

import pytest

from flipdisc.animations.bouncing_dot import BouncingDot
from flipdisc.animations.viewport import Viewport


@pytest.mark.parametrize("speed", [5.0, 10.0, 20.0, 40.0, 60.0, 200.0])
def test_dot_leaves_every_wall(speed):
    """At any speed, the dot keeps crossing the display instead of sticking."""
    anim = BouncingDot(Viewport(28, 28))
    anim.configure(speed_x=speed, speed_y=-speed)
    # Long enough to cross the display several times at the slowest speed
    xs, ys = [], []
    for _ in range(800):
        anim.step(0.05)
        assert 0 <= anim.x < 28 and 0 <= anim.y < 28
        xs.append(anim.x)
        ys.append(anim.y)

    # The last few hundred frames still visit both walls on each axis
    for positions in (xs[-400:], ys[-400:]):
        assert min(positions) == 0
        assert max(positions) == 27


def test_overshoot_stops_at_wall():
    """A multi-pixel step past a wall lands on the wall and turns around."""
    anim = BouncingDot(Viewport(28, 28))
    anim.configure(start_x=26, start_y=5, speed_x=60.0, speed_y=0.0)
    anim.step(0.05)  # 3 px: 26 -> 29, stopped at 27
    assert anim.x == 27
    assert anim.dx < 0
    anim.step(0.05)
    assert anim.x == 24
