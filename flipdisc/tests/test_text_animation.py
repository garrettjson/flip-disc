"""Tests for the text animation."""

import numpy as np
import pytest

from flipdisc.animations.text import TextAnimation
from flipdisc.animations.viewport import Viewport


def test_static_renders_centered():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="HI", mode="static")
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.dtype == np.float32
    # Text should be visible (some non-zero pixels)
    assert frame.sum() > 0


def test_static_too_wide_returns_blank():
    anim = TextAnimation(Viewport(10, 10))
    # "ABCDEFGHIJ" is 39 dots wide even at the smallest size
    anim.configure(text="ABCDEFGHIJ", mode="static")
    assert anim._error is not None
    frame = anim.render_gray()
    assert frame.shape == (10, 10)
    assert frame.sum() == 0


def test_scroll_left_advances():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="HELLO", mode="scroll_left", speed=20.0, loop=False)
    initial_offset = anim._offset
    anim.step(0.1)
    assert anim._offset > initial_offset


def test_scroll_left_completes_no_loop():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="HI", mode="scroll_left", speed=1000.0, loop=False)
    # Step enough for text to fully scroll off
    for _ in range(100):
        anim.step(0.1)
    assert anim.is_complete()


def test_scroll_left_does_not_complete_with_loop():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="HI", mode="scroll_left", speed=1000.0, loop=True)
    for _ in range(100):
        anim.step(0.1)
    assert not anim.is_complete()


def test_scroll_up_wraps_text():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="HELLO WORLD", mode="scroll_up")
    frame = anim.render_gray()
    assert frame.shape == (28, 28)


def test_scroll_down():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="TEST", mode="scroll_down", speed=30.0)
    anim.step(0.5)
    frame = anim.render_gray()
    assert frame.shape == (28, 28)


def test_configure_reset_cycle():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="A", mode="scroll_left", speed=50.0, loop=False)
    for _ in range(50):
        anim.step(0.1)
    assert anim._offset > 0
    anim.reset()
    assert anim._offset == 0.0
    assert not anim.is_complete()


def test_render_before_configure():
    anim = TextAnimation(Viewport(28, 28))
    frame = anim.render_gray()
    assert frame.shape == (28, 28)
    assert frame.sum() == 0


def test_static_centers_text():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="A", mode="static")
    frame = anim.render_gray()
    # "A" is 5x7. Should be centered at roughly (11, 10)
    # Check that pixels exist in the center region
    center_region = frame[8:18, 8:20]
    assert center_region.sum() > 0
    # Edges should be blank
    assert frame[0, 0] == 0.0
    assert frame[27, 27] == 0.0


def test_static_text_too_wide_for_its_size_is_set_smaller():
    anim = TextAnimation(Viewport(28, 28))
    anim.configure(text="Hello!", mode="static")  # 29 wide at 5x8
    assert anim._error is None
    assert anim._font.height == 5
    assert anim.render_gray().any()


@pytest.mark.parametrize(("display", "height"), [(28, 8), (56, 12), (126, 24)])
def test_text_grows_with_the_display(display, height):
    anim = TextAnimation(Viewport(display, display))
    anim.configure(text="Hi", mode="static")
    assert anim._font.height == height


def test_a_layer_sets_text_as_on_its_display_if_it_fits():
    display = Viewport(56, 56)
    tall = TextAnimation(display.region(56, 14))
    tall.configure(text="Hi", mode="static")
    short = TextAnimation(display.region(56, 8))
    short.configure(text="Hi", mode="static")
    assert (tall._font.height, short._font.height) == (12, 8)


def test_a_short_display_keeps_the_design_size():
    anim = TextAnimation(Viewport(28, 8))
    anim.configure(text="HI", mode="static")
    assert anim._font.height == 8


def test_scrolling_speed_follows_the_text_size():
    anim = TextAnimation(Viewport(126, 126))
    anim.configure(text="Hi", mode="scroll_left")
    assert anim._speed_scale == 12 / 5  # letters 12 dots apart, not 5
    anim.configure(mode="scroll_up")
    assert anim._speed_scale == (24 + 1) / (8 + 1)  # lines 25 dots apart, not 9


def test_wrapped_text_keeps_a_letter_gap_from_either_side():
    anim = TextAnimation(Viewport(56, 56))
    anim.configure(text="The quick", mode="scroll_up")
    assert anim._margin == 1
    assert anim._text_image.shape[1] == 54
    assert anim._text_image.shape[0] == 12  # "The quick" fits one line
    anim = TextAnimation(Viewport(1024, 1024))
    anim.configure(text="Hi", mode="scroll_up")
    assert anim._margin == anim._font.spacing > 1
