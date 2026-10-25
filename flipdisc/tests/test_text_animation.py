"""Tests for the text animation."""

import numpy as np

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
    # "ABCDEFGHIJ" = 10*5 + 9*1 = 59px, way too wide for 10px display
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
