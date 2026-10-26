"""Every animation and game runs at every display shape and size we support.

From one 7x7 panel up to 1024x1024: the display is targeted at 56x56 and may
grow past 128, and the code should hold up well beyond that even where the
hardware doesn't.
"""

from datetime import datetime
from unittest import mock

import numpy as np
import pytest

from flipdisc.animations import list_animations
from flipdisc.animations.base import get_animation
from flipdisc.animations.clock import ClockAnimation
from flipdisc.animations.viewport import Viewport
from flipdisc.fonts.loader import load_family
from flipdisc.gfx.postprocessing import apply_processing_pipeline

_SIZES = [(7, 7), (28, 7), (7, 28), (56, 56), (126, 126), (140, 56), (1024, 1024)]

# Params that reach code the defaults don't
_EXTRA = {"clock": {"style": "analog"}, "text": {"text": "HI", "mode": "scroll_left"}}

# fluid's grid has a cell per pixel, so a step at 1024 takes minutes
_TOO_SLOW = {("fluid", 1024)}


@pytest.mark.parametrize(("width", "height"), _SIZES)
@pytest.mark.parametrize("name", list_animations())
def test_renders_at_every_size(name, width, height):
    if (name, width) in _TOO_SLOW:
        pytest.skip("too slow at this size")
    anim = get_animation(name, Viewport(width, height))
    if name in _EXTRA:
        anim.configure(**_EXTRA[name])
    for _ in range(2):
        anim.step(0.05)
        gray = anim.render_gray()
        assert gray.shape == (height, width)
        assert gray.min() >= 0 and gray.max() <= 1
        frame = apply_processing_pipeline(gray, anim.processing_steps)
        assert np.asarray(frame).shape == (height, width)


@pytest.mark.parametrize(("display", "rows"), [(28, 6), (56, 8), (126, 15)])
def test_the_digital_clock_grows_with_the_display(display, rows):
    clock = get_animation("clock", Viewport(display, display))
    lit = np.flatnonzero(clock.render_gray().any(axis=1))
    # Digits fill the rows of a capital: 6 in 5x8, 8 in 6x12, 15 in 12x24
    assert lit.size == rows


@pytest.mark.parametrize("display", [28, 56, 126])
@pytest.mark.parametrize("font", ["spleen", "x11"])
def test_the_clock_colon_sits_in_the_middle_of_the_digits(font, display):
    with mock.patch("flipdisc.animations.clock.datetime") as dt:
        dt.now.return_value = datetime(2026, 10, 25, 12, 34, 0)
        clock = get_animation("clock", Viewport(display, display))
        clock.configure(font=font)
        frame = clock.render_gray() > 0.5
    # Lit columns fall in five runs, 1 2 : 3 4; the colon is the middle one
    columns = np.flatnonzero(frame.any(axis=0))
    runs = np.split(columns, np.flatnonzero(np.diff(columns) > 1) + 1)
    assert len(runs) == 5
    colon = np.flatnonzero(frame[:, runs[2]].any(axis=1))
    digits = np.flatnonzero(frame.any(axis=1))
    middle = (digits[0] + digits[-1]) / 2
    assert abs((colon[0] + colon[-1]) / 2 - middle) <= 0.5


def test_a_wide_colon_gets_more_room():
    sizes = {
        font.name: font
        for name in ("spleen", "x11")
        for font in load_family(name).sizes
    }
    assert ClockAnimation._colon_gap(sizes["spleen/5x8"]) == 1  # a 1-dot colon
    assert ClockAnimation._colon_gap(sizes["x11/6x13"]) == 2  # a 3-dot colon
