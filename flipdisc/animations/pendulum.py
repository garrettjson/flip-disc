"""Pendulum animation - classic physics simulation."""

import math
from typing import override

import numpy as np

from .base import Animation, register_animation

# Converts gravity in m/s^2 to px/s^2; sets how fast the swing looks
_PIXELS_PER_METER = 11.0


@register_animation("pendulum")
class Pendulum(Animation):
    """Simple pendulum physics simulation."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("dither",))

        # Pendulum physics parameters
        self.length = min(width, height) * 0.4  # Pendulum length in pixels
        self.gravity = 9.81 * _PIXELS_PER_METER
        self.damping = 0.998  # Air resistance

        # Pendulum state
        self.angle = math.pi / 4  # Initial angle (45 degrees)
        self.angular_velocity = 0.0

        # Visual parameters
        self.bob_radius = 3
        self.trail_length = 20
        self.trail_positions = []

        # Anchor point (top center)
        self.anchor_x = width / 2
        self.anchor_y = height * 0.1

    @override
    def configure(self, **params):
        """Configure pendulum parameters."""
        super().configure(**params)

        if "gravity" in params:
            self.gravity = float(params["gravity"]) * _PIXELS_PER_METER
        if "damping" in params:
            self.damping = float(params["damping"])
        if "length" in params:
            self.length = float(params["length"])
        if "initial_angle" in params:
            self.angle = float(params["initial_angle"])
            self.angular_velocity = 0.0

    @override
    def step(self, dt: float) -> None:
        """Advance pendulum physics."""
        self.current_time += dt

        # Pendulum physics: θ'' = -(g/L) * sin(θ) - damping * θ'
        angular_acceleration = -(self.gravity / self.length) * math.sin(self.angle)
        angular_acceleration -= (1 - self.damping) * self.angular_velocity

        # Euler integration
        self.angular_velocity += angular_acceleration * dt
        self.angle += self.angular_velocity * dt

        # Calculate bob position
        bob_x = self.anchor_x + self.length * math.sin(self.angle)
        bob_y = self.anchor_y + self.length * math.cos(self.angle)

        # Update trail
        self.trail_positions.append((bob_x, bob_y))
        if len(self.trail_positions) > self.trail_length:
            self.trail_positions.pop(0)

    @override
    def render_gray(self) -> np.ndarray:
        """Render pendulum to grayscale."""
        frame = np.zeros((self.height, self.width), dtype=np.float32)

        if not self.trail_positions:
            return frame

        # Draw pendulum rod
        bob_x, bob_y = self.trail_positions[-1]
        self._draw_line(frame, self.anchor_x, self.anchor_y, bob_x, bob_y, 0.6)

        # Draw anchor point
        self._draw_circle(frame, self.anchor_x, self.anchor_y, 2, 1.0)

        # Draw trail (fading)
        for i, (x, y) in enumerate(self.trail_positions):
            intensity = (i + 1) / len(self.trail_positions) * 0.8
            self._draw_circle(frame, x, y, 1, intensity)

        # Draw bob
        self._draw_circle(frame, bob_x, bob_y, self.bob_radius, 1.0)

        return frame

    def _draw_circle(
        self, frame: np.ndarray, cx: float, cy: float, radius: float, intensity: float
    ):
        """Draw anti-aliased circle."""
        y_min = max(0, int(cy - radius - 1))
        y_max = min(self.height, int(cy + radius + 2))
        x_min = max(0, int(cx - radius - 1))
        x_max = min(self.width, int(cx + radius + 2))

        for y in range(y_min, y_max):
            for x in range(x_min, x_max):
                dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                if dist <= radius:
                    # Anti-aliasing
                    alpha = max(0, min(1, radius - dist + 0.5))
                    frame[y, x] = max(frame[y, x], intensity * alpha)

    def _draw_line(
        self,
        frame: np.ndarray,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        intensity: float,
    ):
        """Draw anti-aliased line using Bresenham-like algorithm."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        steps = max(dx, dy)

        if steps == 0:
            return

        x_step = (x1 - x0) / steps
        y_step = (y1 - y0) / steps

        for i in range(int(steps) + 1):
            x = x0 + i * x_step
            y = y0 + i * y_step

            if 0 <= x < self.width and 0 <= y < self.height:
                # Simple anti-aliasing
                x_int, y_int = int(x), int(y)
                x_frac, y_frac = x - x_int, y - y_int

                # Distribute intensity to neighboring pixels
                for dy in range(2):
                    for dx in range(2):
                        px, py = x_int + dx, y_int + dy
                        if 0 <= px < self.width and 0 <= py < self.height:
                            weight = (1 - abs(dx - x_frac)) * (1 - abs(dy - y_frac))
                            frame[py, px] = max(frame[py, px], intensity * weight * 0.5)
