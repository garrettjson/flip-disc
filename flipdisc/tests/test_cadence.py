"""Whole-step motion must land on an even rhythm at any requested rate."""

from itertools import pairwise

import pytest

from flipdisc.animations.cadence import Cadence
from flipdisc.animations.precipitation import RainEffect
from flipdisc.animations.text import TextAnimation

FPS = 20
DT = 1 / FPS


def _gaps(steps: list[int]) -> set[int]:
    """Distinct frame counts between consecutive moves."""
    moves = [i for i, n in enumerate(steps) if n]
    return {b - a for a, b in pairwise(moves)}


@pytest.mark.parametrize("rate", [0.67, 2.0, 4.67, 6.67, 7.0, 10.0, 13.0, 19.0])
def test_slow_rates_move_one_step_at_a_constant_interval(rate):
    cadence = Cadence()
    steps = [cadence.advance(rate, DT) for _ in range(400)]
    assert set(steps) <= {0, 1}
    assert len(_gaps(steps)) == 1


@pytest.mark.parametrize(("rate", "per_frame"), [(20.0, 1), (40.0, 2), (47.0, 2)])
def test_fast_rates_move_the_same_whole_amount_every_frame(rate, per_frame):
    cadence = Cadence()
    assert {cadence.advance(rate, DT) for _ in range(100)} == {per_frame}


def test_zero_and_negative_rates_never_move():
    cadence = Cadence()
    assert all(cadence.advance(0.0, DT) == 0 for _ in range(50))
    assert all(cadence.advance(-5.0, DT) == 0 for _ in range(50))


def test_snapped_rate_matches_what_advance_delivers():
    for rate in (0.67, 4.67, 7.0, 13.0, 20.0, 47.0):
        cadence = Cadence()
        moved = sum(cadence.advance(rate, DT) for _ in range(FPS * 60))
        assert moved / 60 == pytest.approx(Cadence.snapped_rate(rate, DT), rel=0.02)


def test_snapped_rate_examples():
    assert Cadence.snapped_rate(7.0, DT) == pytest.approx(20 / 3)  # every 3 frames
    assert Cadence.snapped_rate(10.0, DT) == pytest.approx(10.0)  # every 2 frames
    assert Cadence.snapped_rate(47.0, DT) == pytest.approx(40.0)  # 2 per frame
    assert Cadence.snapped_rate(0.0, DT) == 0.0


def test_reset_restarts_the_count():
    cadence = Cadence()
    assert [cadence.advance(10.0, DT) for _ in range(3)] == [0, 1, 0]
    cadence.reset()
    assert [cadence.advance(10.0, DT) for _ in range(2)] == [0, 1]


def test_text_scrolls_at_an_even_cadence():
    anim = TextAnimation(28, 28)
    anim.configure(text="HELLO WORLD", mode="scroll_left")  # default speed
    offsets = []
    for _ in range(300):
        anim.step(DT)
        offsets.append(anim._offset)
    steps = [b - a for a, b in pairwise(offsets)]
    assert len(_gaps(steps)) == 1


def test_rain_falls_at_an_even_cadence():
    effect = RainEffect(cloud_cols_range=(13, 22), spawn_y=0, max_y=10_000)
    effect.step(DT)
    while not effect._particles:
        effect.step(DT)
    drop = effect._particles[0]
    ys = []
    for _ in range(300):
        effect.step(DT)
        ys.append(drop.y)
    steps = [b - a for a, b in pairwise(ys)]
    assert set(steps) <= {0, 1}
    assert len(_gaps(steps)) == 1
