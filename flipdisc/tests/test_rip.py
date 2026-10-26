"""Tests for the rip animation."""

from itertools import pairwise

import numpy as np
import pytest

from flipdisc.animations.rip import Rip
from flipdisc.animations.viewport import Viewport


def _run(anim: Rip, frames: int, dt: float = 0.05) -> list[np.ndarray]:
    out = []
    for _ in range(frames):
        anim.step(dt)
        out.append(anim.render_gray())
    return out


def _solid(frame: np.ndarray) -> float | None:
    """The frame's colour if every dot is the same, else None."""
    return float(frame.flat[0]) if np.ptp(frame) == 0 else None


def _rips(frames: list[np.ndarray]) -> list[list[np.ndarray]]:
    """The runs of frames in which a sheet was partly torn."""
    runs: list[list[np.ndarray]] = []
    torn_before = False
    for frame in frames:
        torn = _solid(frame) is None
        if torn and not torn_before:
            runs.append([])
        if torn:
            runs[-1].append(frame)
        torn_before = torn
    return runs


def test_render_shape_and_values():
    np.random.seed(0)
    anim = Rip(Viewport(28, 28))
    for frame in _run(anim, 60):
        assert frame.shape == (28, 28)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}


def test_sheets_alternate_black_and_white():
    np.random.seed(0)
    anim = Rip(Viewport(28, 28))
    # At 20 fps each cycle is 0.5 s at rest plus a 0.4 s rip: 18 frames
    frames = [np.zeros((28, 28)), *_run(anim, 18 * 4 + 6)]
    # A frame in the middle of each rest
    resting = [_solid(frames[i]) for i in range(5, len(frames), 18)]
    assert resting == [0.0, 1.0, 0.0, 1.0, 0.0]


def test_rests_for_the_pause_between_rips():
    np.random.seed(0)
    frames = _run(Rip(Viewport(28, 28)), 18 * 3)
    torn = [_solid(frame) is None for frame in frames]
    # The first rip shows on the frame after 0.5 s, and each starts 18 frames
    # after the one before
    starts = [i for i in range(len(torn)) if torn[i] and (i == 0 or not torn[i - 1])]
    assert starts == [10, 28, 46]
    # The display rests on each new sheet for at least the pause (10 frames)
    for start, next_start in pairwise(starts):
        rest = next_start - start - sum(torn[start:next_start])
        assert rest >= 10


def test_no_pause_rips_back_to_back():
    np.random.seed(0)
    anim = Rip(Viewport(28, 28))
    anim.configure(pause=0)
    frames = _run(anim, 8 * 4)
    starts = [i for i in range(len(frames)) if i % 8 == 0]
    assert all(_solid(frames[i]) is None for i in starts)


def test_a_rip_starts_as_a_crack_right_across_the_display():
    for seed in range(20):
        np.random.seed(seed)
        crack = _rips(_run(Rip(Viewport(28, 28)), 12))[0][0]
        rows, cols = np.nonzero(crack)
        # A thin line from one edge of the display to another
        assert crack.sum() < 2.5 * 28
        edges = {
            "top": (rows == 0).any(),
            "bottom": (rows == 27).any(),
            "left": (cols == 0).any(),
            "right": (cols == 27).any(),
        }
        assert sum(edges.values()) >= 2, seed


def test_the_hole_only_grows():
    for seed in range(10):
        np.random.seed(seed)
        anim = Rip(Viewport(28, 28))
        anim.configure(rip_time=2)  # many frames to compare
        for rip in _rips(_run(anim, 60)):
            for before, after in pairwise(rip):
                assert (after >= before).all()


def test_the_hole_is_widest_where_the_tear_is_grabbed():
    for seed in range(10):
        np.random.seed(seed)
        anim = Rip(Viewport(28, 28))
        anim.configure(rip_time=2)
        _run(anim, 10 + 20)  # halfway through the rip
        tear = anim._tear
        hole = anim.render_gray().astype(bool)
        # How far the hole reaches from the tear line near its middle, and
        # near its ends
        middle = tear.distance[hole & (tear.profile > 0.9)].max()
        ends = tear.distance[hole & (tear.profile < 0.5)].max()
        assert middle > ends + 2, seed


def test_no_bulge_pulls_straight_edges():
    np.random.seed(0)
    anim = Rip(Viewport(28, 28))
    anim.configure(bulge=0, rip_time=2)
    _run(anim, 10 + 12)
    tear = anim._tear
    hole = anim.render_gray().astype(bool)
    # Every dot nearer the tear line than the furthest one uncovered is
    # uncovered too: the edges are parallel to the line
    assert hole[tear.distance < tear.distance[hole].max()].all()


def test_reset():
    np.random.seed(0)
    anim = Rip(Viewport(28, 28))
    _run(anim, 25)
    anim.reset(seed=1)
    assert anim.current_time == 0.0
    assert _solid(anim.render_gray()) == 0.0
    assert [_solid(f) for f in _run(anim, 10)] == [0.0] * 10


@pytest.mark.parametrize(("width", "height"), [(1, 1), (7, 3), (28, 7), (56, 56)])
def test_other_sizes(width, height):
    np.random.seed(0)
    frames = _run(Rip(Viewport(width, height)), 18 * 2 + 1)
    assert all(frame.shape == (height, width) for frame in frames)
    assert _solid(frames[5]) == 0.0
    assert _solid(frames[18 + 5]) == 1.0
    if width * height > 1:
        assert len(_rips(frames)) == 2
