"""Static image animation — renders a single PNG frame on the display."""

from typing import override

import numpy as np

from flipdisc.animations.clip import _blit_fit
from flipdisc.gfx.images import load_gray

from .base import Animation, register_animation
from .params import Param


@register_animation("image")
class ImageAnimation(Animation):
    """Displays a static PNG image, center-fitted to the layer dimensions.

    The image is loaded and binarized at configure time. Updating ``src``
    swaps the image live without restarting the animation::

        POST / anim / image
        {"src": "assets/images/cloud.png"}

        POST / animations / configure
        {"layer.icon.src": "assets/images/sun.png"}
    """

    PARAMS = (Param("src", str, None, nullable=True),)

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))
        self._frame: np.ndarray | None = None

    @override
    def on_configure(self, **params) -> None:
        if params.get("src") is not None:
            self._frame = load_gray(params["src"])

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt

    @override
    def render_gray(self) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        if self._frame is not None:
            _blit_fit(canvas, self._frame, "center")
        return canvas
