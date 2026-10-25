"""Tests for the rain splash animation."""

import numpy as np
import pytest

from flipdisc.animations.rain_splash import RainSplash
from flipdisc.animations.viewport import Viewport


def _quiet(width: int = 28, height: int = 28) -> RainSplash:
    """An animation with no random drops, for placing splashes by hand."""
    anim = RainSplash(Viewport(width, height))
    anim.configure(drops_per_second=0)
    return anim


def _lit(anim: RainSplash) -> set[tuple[int, int]]:
    ys, xs = np.nonzero(anim.render_gray())
    return set(zip(xs.tolist(), ys.tolist(), strict=True))


def test_render_shape_and_values():
    np.random.seed(0)
    anim = RainSplash(Viewport(28, 28))
    for _ in range(40):
        anim.step(0.05)
        frame = anim.render_gray()
        assert frame.shape == (28, 28)
        assert frame.dtype == np.float32
        assert set(np.unique(frame)) <= {0.0, 1.0}


def test_small_splash_is_one_dot():
    anim = _quiet()
    anim._add_ripple(10, 12, big=False, max_radius=3)
    assert _lit(anim) == {(10, 12)}


def test_big_splash_is_a_two_by_two_block():
    anim = _quiet()
    anim._add_ripple(10, 12, big=True, max_radius=3)
    assert _lit(anim) == {(10, 12), (11, 12), (10, 13), (11, 13)}


def test_ring_expands_one_pixel_per_step_then_vanishes():
    anim = _quiet()
    anim.configure(ring_speed=10)  # one pixel every 2 frames at 20 fps
    anim._add_ripple(14, 14, big=False, max_radius=3)

    radii = []
    for _ in range(10):
        anim.step(0.05)
        lit = _lit(anim)
        if not lit:
            radii.append(None)
            continue
        dist = {round(float(np.hypot(x - 14, y - 14))) for x, y in lit}
        assert len(dist) == 1, "a ring is one radius wide"
        radii.append(dist.pop())

    assert radii == [0, 1, 1, 2, 2, 3, 3, None, None, None]


def test_big_ring_surrounds_the_splash():
    anim = _quiet()
    anim.configure(ring_speed=20)  # one pixel per frame
    anim._add_ripple(10, 10, big=True, max_radius=2)
    anim.step(0.05)
    ring = _lit(anim)
    assert ring.isdisjoint({(10, 10), (11, 10), (10, 11), (11, 11)})
    assert {(9, 10), (12, 11), (10, 9), (11, 12)} <= ring


def test_ring_sizes_follow_the_requested_distribution():
    np.random.seed(1)
    anim = RainSplash(Viewport(28, 28))
    anim.configure(big_drop_chance=0, ring_size=5, ring_size_spread=1.5)
    for _ in range(500):
        anim._spawn()
    sizes = np.array([r.max_radius for r in anim._ripples])
    assert abs(sizes.mean() - 5) < 0.3
    assert sizes.min() >= 1


def test_big_drops_make_bigger_rings_on_average():
    np.random.seed(2)
    anim = RainSplash(Viewport(28, 28))
    anim.configure(big_drop_chance=0.5)
    for _ in range(500):
        anim._spawn()
    small = [r.max_radius for r in anim._ripples if not r.big]
    big = [r.max_radius for r in anim._ripples if r.big]
    assert np.mean(big) > np.mean(small) + 1


def test_no_rain_stays_blank():
    anim = _quiet()
    for _ in range(40):
        anim.step(0.05)
    assert not anim.render_gray().any()


def test_drop_rate_controls_how_many_splashes_start():
    np.random.seed(3)
    anim = RainSplash(Viewport(28, 28))
    anim.configure(drops_per_second=10, ring_size=30)  # rings outlive the run
    for _ in range(100):  # 5 seconds
        anim.step(0.05)
    assert 30 <= len(anim._ripples) <= 70


def test_reset_clears_ripples():
    anim = _quiet()
    anim._add_ripple(3, 3, big=False, max_radius=5)
    anim.reset()
    assert not anim.render_gray().any()


@pytest.mark.parametrize(("width", "height"), [(7, 7), (14, 7), (28, 7), (1, 1)])
def test_other_sizes(width, height):
    np.random.seed(4)
    anim = RainSplash(Viewport(width, height))
    anim.configure(drops_per_second=20, big_drop_chance=0.5)
    for _ in range(40):
        anim.step(0.05)
        assert anim.render_gray().shape == (height, width)
