"""Tests for the sandpile animation."""

import numpy as np
import pytest

from flipdisc.animations.sandpile import Sandpile


def _run(anim: Sandpile, seconds: float, dt: float = 0.05) -> None:
    for _ in range(round(seconds / dt)):
        anim.step(dt)


def _heights(anim: Sandpile) -> np.ndarray:
    return np.array([len(c) for c in anim._columns])


def _grains(anim: Sandpile) -> int:
    return int(_heights(anim).sum()) + len(anim._falling)


def test_render_shape_and_values():
    np.random.seed(0)
    anim = Sandpile(28, 28)
    for _ in range(100):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (28, 28)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}


def test_stream_falls_from_the_pour_position():
    anim = Sandpile(28, 28)
    anim.configure(pour_position=0.25, sweep_speed=0)
    _run(anim, 0.5)  # before anything lands
    lit_columns = set(np.nonzero(anim.render_gray())[1].tolist())
    assert lit_columns == {round(0.25 * 27)}


def test_stronger_gravity_lands_sooner():
    def first_landing(gravity: float) -> int:
        anim = Sandpile(28, 28)
        anim.configure(gravity=gravity)
        for frame in range(200):
            anim.step(0.05)
            if _heights(anim).any():
                return frame
        raise AssertionError("nothing landed")

    assert first_landing(200) < first_landing(60) < first_landing(15)


def test_poured_grains_are_conserved():
    np.random.seed(1)
    anim = Sandpile(28, 28)
    anim.configure(pour_rate=10, lifespan=600)
    _run(anim, 10)
    assert _grains(anim) == 100


def test_higher_friction_builds_a_taller_narrower_pile():
    def pile(friction: float) -> np.ndarray:
        np.random.seed(2)
        anim = Sandpile(28, 28)
        anim.configure(friction=friction, lifespan=600, pour_rate=10, sweep_speed=0)
        _run(anim, 12)
        anim.configure(pour_rate=0)
        _run(anim, 5)
        return _heights(anim)

    sand, marbles = pile(1.0), pile(0.0)
    assert sand.sum() == marbles.sum()
    assert sand.max() > marbles.max() + 4
    assert np.count_nonzero(sand) < np.count_nonzero(marbles)


@pytest.mark.parametrize("friction", [0.0, 0.4, 1.0])
def test_pile_comes_to_rest_when_pouring_stops(friction):
    np.random.seed(3)
    anim = Sandpile(28, 28)
    anim.configure(friction=friction, lifespan=600)
    _run(anim, 10)
    anim.configure(pour_rate=0)
    _run(anim, 10)
    settled = anim.render_gray()
    _run(anim, 5)
    assert not anim._falling
    assert np.array_equal(anim.render_gray(), settled), "a still pile flips no dots"


def test_lifespan_limits_the_pile_size():
    np.random.seed(4)
    anim = Sandpile(28, 28)
    anim.configure(pour_rate=10, lifespan=5)
    _run(anim, 30)
    # Grains last 5 s ± 25% once landed, so about 10/s * 5 s are in the pile
    assert 35 <= _heights(anim).sum() <= 65


def test_pile_centres_under_the_pour():
    np.random.seed(5)
    anim = Sandpile(28, 28)
    anim.configure(pour_position=0.2, lifespan=600, sweep_speed=0)
    _run(anim, 8)
    heights = _heights(anim)
    centre = (heights * np.arange(28)).sum() / heights.sum()
    assert abs(centre - 0.2 * 27) < 3


def test_stream_is_not_bunched_at_the_spout():
    anim = Sandpile(28, 28)
    anim.configure(sweep_speed=0)  # default pour rate
    for _ in range(16):  # stream established, nothing landed yet
        anim.step(0.05)
        # Leaving the spout at speed, no two grains share a pixel, so every
        # grain in flight is visible
        rows = [int(g.y) for g in anim._falling]
        assert len(set(rows)) == len(rows)


def test_spout_sweeps_side_to_side():
    anim = Sandpile(28, 28)
    anim.configure(sweep_speed=0.5)
    positions = set()
    for _ in range(40):  # one full cycle
        anim.step(0.05)
        positions.add(anim._spout_x())
    # 0.5 ± 0.4 of the width
    assert min(positions) <= round(0.1 * 27) + 1
    assert max(positions) >= round(0.9 * 27) - 1


def test_no_sweep_holds_the_spout_still():
    anim = Sandpile(28, 28)
    anim.configure(sweep_speed=0, pour_position=0.7)
    for _ in range(40):
        anim.step(0.05)
        assert anim._spout_x() == round(0.7 * 27)


def test_static_movement_holds_the_spout_still():
    anim = Sandpile(28, 28)
    anim.configure(movement="static", sweep_speed=0.5, pour_position=0.3)
    for _ in range(40):
        anim.step(0.05)
        assert anim._spout_x() == round(0.3 * 27)


def _spout_path(movement: str, seconds: float) -> np.ndarray:
    anim = Sandpile(28, 28)
    anim.configure(movement=movement, sweep_speed=0.1)
    path = []
    for _ in range(round(seconds / 0.05)):
        anim.step(0.05)
        path.append(anim._spout_x())
    return np.array(path)


def test_gaussian_movement_dwells_in_the_middle():
    gaussian, sweep = _spout_path("gaussian", 10), _spout_path("sweep", 10)
    # Reaches the same edges as the sweep
    assert gaussian.min() == sweep.min()
    assert gaussian.max() == sweep.max()

    def middle_share(path: np.ndarray) -> float:
        return float(np.mean(abs(path - 13.5) < 4))

    # Within 4 columns of the centre (0.37 of the sweep's amplitude), a normal
    # distribution truncated at 2 standard deviations spends about 57% of its
    # time; a sine wave 24%
    assert middle_share(gaussian) > 0.45
    assert middle_share(sweep) < 0.3
    # It moves fastest at the edges
    speed = abs(np.diff(gaussian))
    near_edge = abs(gaussian[1:] - 13.5) > 8
    assert speed[near_edge].mean() > 3 * speed[~near_edge].mean()


def test_random_movement_wanders_smoothly_within_the_sweep():
    np.random.seed(8)
    path = _spout_path("random", 60)
    # 0.5 ± 0.4 of the width
    assert path.min() >= round(0.1 * 27)
    assert path.max() <= round(0.9 * 27)
    assert path.max() - path.min() > 12
    # Glides rather than jumping: under one column per frame at 0.1 Hz
    assert abs(np.diff(path)).max() <= 1
    # Turns around at random points, not just at the edges
    moves = np.sign(np.diff(path))
    directions = moves[moves != 0]
    turns = path[1:][moves != 0][:-1][directions[1:] != directions[:-1]]
    assert len(set(turns.tolist())) >= 4


def test_full_display_stops_accepting_grains():
    np.random.seed(6)
    anim = Sandpile(7, 7)
    anim.configure(pour_rate=60, lifespan=600, friction=0)
    _run(anim, 20)
    assert (_heights(anim) == 7).all()
    assert anim.render_gray().all()


def test_reset_clears_everything():
    anim = Sandpile(28, 28)
    _run(anim, 5)
    anim.reset()
    assert _grains(anim) == 0
    assert not anim.render_gray().any()


@pytest.mark.parametrize(("width", "height"), [(7, 7), (14, 7), (28, 7), (1, 1)])
def test_other_sizes(width, height):
    np.random.seed(7)
    anim = Sandpile(width, height)
    for _ in range(100):
        anim.step(0.05)
        assert anim.render_gray().shape == (height, width)
