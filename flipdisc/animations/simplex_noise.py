"""Simplex noise animation.

``scale`` is the size of the noise's features in dots on the 28-dot design
display; they grow with the display, so a bigger one shows the same pattern
with finer edges (see ``scaling.py``).
"""

from typing import override

import numpy as np

from flipdisc.gfx.noise import permutation, simplex3

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Lowers the noise frequency to match opensimplex, which this animation used
# before: at every scale and speed, blob size and dots flipped per frame come
# out within about a percent, so `scale` and `speed` keep their meaning.
_FREQUENCY = 0.56


@register_animation("simplex_noise")
class SimplexNoise(Animation):
    """Animated simplex noise pattern."""

    PARAMS = (
        Param("scale", float, 4.0, min=0.1, max=50, step=0.5),
        Param("speed", float, 1.0, min=0, max=20, step=0.2, unit="/s"),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=("binarize",))

        # Parameters
        self.feature_size = self.params["scale"]  # Spatial scale of the noise
        self.speed = self.params["speed"]  # Noise-time units per second
        self.i = 0.0  # Current time offset

        self._perm = permutation()
        # A row of x and a column of y, broadcast to the grid by simplex3, in
        # dots on the design display
        frequency = _FREQUENCY / self.scale.factor
        self._x = np.arange(self.width)[None, :] * frequency
        self._y = np.arange(self.height)[:, None] * frequency

    @override
    def on_configure(self, **params):
        if "scale" in params:
            self.feature_size = params["scale"]
        if "speed" in params:
            self.speed = params["speed"]

    @override
    def step(self, dt: float) -> None:
        """Advance noise animation through time."""
        self.current_time += dt
        self.i += self.speed * dt

    @override
    def reset(self, seed: int | None = None) -> None:
        """Start over; a seed picks a different noise field."""
        super().reset(seed)
        self.i = 0.0
        if seed is not None:
            self._perm = permutation(seed)

    @override
    def render_gray(self) -> np.ndarray:
        """Render simplex noise to grayscale."""
        noise = simplex3(
            self._x / self.feature_size,
            self._y / self.feature_size,
            self.i * _FREQUENCY,
            self._perm,
        )
        # Map from about [-1, 1] to [0, 1]; the extremes overshoot slightly
        return np.clip((noise + 1.0) / 2.0, 0.0, 1.0).astype(np.float32)
