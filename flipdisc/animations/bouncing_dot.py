"""Simple bouncing dot animation."""

from typing import override

import numpy as np

from .base import Animation, register_animation
from .cadence import Cadence
from .params import Param
from .viewport import Viewport


@register_animation("bouncing_dot")
class BouncingDot(Animation):
    """Simple bouncing dot"""

    PARAMS = (
        Param("start_x", int, 2, min=0),
        Param("start_y", int, 5, min=0),
        Param("speed_x", float, 20.0, min=-200, max=200, step=5, unit="px/s"),
        Param("speed_y", float, 40.0, min=-200, max=200, step=5, unit="px/s"),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=("binarize",))

        # Dot position (whole pixels)
        self.x = min(self.params["start_x"], self.width - 1)
        self.y = min(self.params["start_y"], self.height - 1)

        # Velocity in pixels per second; the sign is the direction
        self.dx = self.params["speed_x"]
        self.dy = self.params["speed_y"]
        self._cadence_x = Cadence()
        self._cadence_y = Cadence()

    @override
    def on_configure(self, **params):
        if "start_x" in params:
            self.x = min(params["start_x"], self.width - 1)
        if "start_y" in params:
            self.y = min(params["start_y"], self.height - 1)
        if "speed_x" in params:
            self.dx = params["speed_x"]
        if "speed_y" in params:
            self.dy = params["speed_y"]

    @override
    def step(self, dt: float) -> None:
        """Advance dot position and bounce off the edges."""
        self.current_time += dt

        # Clamp position in case display size changed
        self.x = max(0, min(self.x, self.width - 1))
        self.y = max(0, min(self.y, self.height - 1))

        # Advance position
        step_x = self._cadence_x.advance(abs(self.dx), dt)
        step_y = self._cadence_y.advance(abs(self.dy), dt)
        self.x += step_x if self.dx > 0 else -step_x
        self.y += step_y if self.dy > 0 else -step_y

        # Bounce off walls
        if self.x <= 0 or self.x >= self.width - 1:
            self.dx *= -1
            self.x = max(0, min(self.x, self.width - 1))

        if self.y <= 0 or self.y >= self.height - 1:
            self.dy *= -1
            self.y = max(0, min(self.y, self.height - 1))

    @override
    def render_gray(self) -> np.ndarray:
        """Render bouncing dot as single pixel."""
        frame = np.zeros((self.height, self.width), dtype=np.float32)

        # Set single pixel at current position
        frame[self.y, self.x] = 1.0

        return frame
