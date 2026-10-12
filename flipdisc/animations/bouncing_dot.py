"""Simple bouncing dot animation."""

from typing import override

import numpy as np

from .base import Animation, register_animation


@register_animation("bouncing_dot")
class BouncingDot(Animation):
    """Simple bouncing dot"""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))

        # Dot position in pixels (rounded when drawn)
        self.x = 2.0
        self.y = 5.0

        # Velocity in pixels per second
        self.dx = 20.0
        self.dy = 40.0

    @override
    def configure(self, **params):
        """Configure bouncing dot parameters."""
        super().configure(**params)

        if "start_x" in params:
            self.x = float(max(0, min(int(params["start_x"]), self.width - 1)))
        if "start_y" in params:
            self.y = float(max(0, min(int(params["start_y"]), self.height - 1)))
        if "speed_x" in params:
            self.dx = float(params["speed_x"])
        if "speed_y" in params:
            self.dy = float(params["speed_y"])

    @override
    def step(self, dt: float) -> None:
        """Advance dot position and bounce off the edges."""
        self.current_time += dt

        # Clamp position in case display size changed
        self.x = max(0, min(self.x, self.width - 1))
        self.y = max(0, min(self.y, self.height - 1))

        # Advance position
        self.x += self.dx * dt
        self.y += self.dy * dt

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
        frame[round(self.y), round(self.x)] = 1.0

        return frame
