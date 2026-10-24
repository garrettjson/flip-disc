"""Tests for the sort animation and its algorithms."""

import numpy as np
import pytest

from flipdisc.animations.sorting.base import _ALGORITHMS as ALGORITHMS
from flipdisc.animations.sorting.base import SortAnimation, list_algorithms
from flipdisc.exceptions import AnimationError


def _run_until(anim: SortAnimation, phase: str, limit: int = 5000) -> int:
    """Step until the animation enters ``phase``; return the frames taken."""
    for frame in range(1, limit + 1):
        anim.step(0.05)
        if anim._phase == phase:
            return frame
    raise AssertionError(f"never reached {phase}")


def _bars(anim: SortAnimation) -> np.ndarray:
    """Height of each column's bar, read from the frame."""
    return (anim.render_gray() > 0.5).sum(axis=0)


# Algorithms too slow to finish on many bars, and the most they're tested on
_MAX_COUNT = frozendict({"bogo": 5})


@pytest.mark.parametrize("name", list_algorithms())
@pytest.mark.parametrize("count", [1, 2, 3, 5, 10, 28])
def test_algorithm_sorts(name, count):
    if count > _MAX_COUNT.get(name, count):
        pytest.skip(f"{name} would take too long on {count} bars")
    np.random.seed(count)
    rng = np.random.default_rng(count)
    for _ in range(5):
        values = (rng.permutation(count) + 1).tolist()
        for highlight in ALGORITHMS[name](values):
            assert all(0 <= i < count for i in highlight)
        assert values == list(range(1, count + 1))


@pytest.mark.parametrize("name", list_algorithms())
def test_algorithm_handles_sorted_and_reversed_input(name):
    count = _MAX_COUNT.get(name, 256)  # the most bars there can be
    for values in (list(range(1, count + 1)), list(range(count, 0, -1))):
        np.random.seed(0)
        for _ in ALGORITHMS[name](values):
            pass
        assert values == list(range(1, count + 1))


@pytest.mark.parametrize("name", list_algorithms())
def test_every_algorithm_runs_to_done(name):
    np.random.seed(0)
    anim = SortAnimation(28, 28)
    anim.configure(algorithm=name, bars=5)
    _run_until(anim, "done")
    assert anim._values == [1, 2, 3, 4, 5]


def test_render_shape_and_dtype():
    anim = SortAnimation(28, 28)
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    assert set(np.unique(frame)) <= {0.0, 1.0}


def test_starts_as_a_staircase():
    anim = SortAnimation(28, 28)
    assert _bars(anim).tolist() == list(range(1, 29))


def test_shuffles_then_sorts_then_finishes():
    np.random.seed(0)
    anim = SortAnimation(28, 28)
    _run_until(anim, "sort")
    assert anim._values != sorted(anim._values)
    assert not anim.is_complete()
    _run_until(anim, "done")
    assert anim.is_complete()
    assert anim._values == list(range(1, 29))
    assert anim._highlight == ()
    assert _bars(anim).tolist() == list(range(1, 29))


def test_holds_the_sorted_bars_once_done():
    np.random.seed(0)
    anim = SortAnimation(28, 28)
    _run_until(anim, "done")
    finished = anim.render_gray()
    for _ in range(200):
        anim.step(0.05)
    assert anim._phase == "done"
    assert np.array_equal(anim.render_gray(), finished)


def test_reconfiguring_after_done_runs_again():
    np.random.seed(0)
    anim = SortAnimation(28, 28)
    _run_until(anim, "done")
    anim.configure(bars=14)
    assert not anim.is_complete()
    assert anim._phase == "shuffle"


def test_speed_sets_operations_per_second():
    # The same seed gives both the same shuffle
    np.random.seed(0)
    slow_frames = _run_until(SortAnimation(28, 28), "sweep")
    np.random.seed(0)
    fast = SortAnimation(28, 28)
    fast.configure(speed=40)
    fast_frames = _run_until(fast, "sweep")
    assert fast_frames < 0.6 * slow_frames


def test_highlight_invert_flips_the_compared_columns():
    anim = SortAnimation(28, 28)
    anim._highlight = (3, 4)
    frame = anim.render_gray() > 0.5
    assert frame[:, 3].sum() == 28 - 4
    assert frame[:, 4].sum() == 28 - 5
    assert frame[:, 5].sum() == 6


def test_highlight_cap_keeps_only_the_top_dot():
    anim = SortAnimation(28, 28)
    anim.configure(highlight="cap")
    anim._highlight = (9,)
    frame = anim.render_gray() > 0.5
    assert frame[:, 9].sum() == 1
    assert frame[28 - 10, 9]


def test_highlight_none():
    anim = SortAnimation(28, 28)
    anim.configure(highlight="none")
    anim._highlight = (9,)
    assert _bars(anim).tolist() == list(range(1, 29))


def test_fewer_bars_are_wider_and_centred():
    anim = SortAnimation(28, 28)
    anim.configure(bars=5)
    heights = _bars(anim)
    # 5 bars of 5 columns, with the 3 spare columns split either side
    assert heights[:1].tolist() == [0]
    assert heights[1:26].tolist() == np.repeat([6, 12, 17, 23, 28], 5).tolist()
    assert heights[26:].tolist() == [0, 0]


def test_more_bars_than_rows_all_show():
    anim = SortAnimation(56, 28)
    heights = _bars(anim)
    assert len(anim._values) == 56
    assert heights.min() == 1
    assert heights.max() == 28


def test_bars_are_capped_at_the_width():
    anim = SortAnimation(28, 28)
    anim.configure(bars=100)
    assert len(anim._values) == 28


def test_changing_algorithm_restarts():
    anim = SortAnimation(28, 28)
    _run_until(anim, "sort")
    anim.configure(algorithm="bubble")
    assert anim._phase == "shuffle"
    assert anim._values == list(range(1, 29))


def test_unknown_algorithm_is_rejected():
    anim = SortAnimation(28, 28)
    with pytest.raises(AnimationError):
        anim.configure(algorithm="sleep")


def test_reset():
    anim = SortAnimation(28, 28)
    _run_until(anim, "sort")
    anim.reset(seed=1)
    assert anim.current_time == 0.0
    assert not anim.is_complete()
    assert anim._phase == "shuffle"
    assert anim._values == list(range(1, 29))


def test_different_sizes():
    for w, h in [(1, 7), (14, 7), (28, 28), (56, 28)]:
        anim = SortAnimation(w, h)
        for _ in range(50):
            anim.step(0.05)
        assert anim.render_gray().shape == (h, w)
