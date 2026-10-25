"""Every animation and game runs at every display shape and size we support.

From one 7x7 panel up to 1024x1024: the display is targeted at 56x56 and may
grow past 128, and the code should hold up well beyond that even where the
hardware doesn't.
"""

import numpy as np
import pytest

from flipdisc.animations import list_animations
from flipdisc.animations.base import get_animation
from flipdisc.animations.viewport import Viewport
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
