"""Rotating 3D wireframe cube animation.

The cube's size is a fraction of the display; its lines are drawn crisp, one
dot wide on a 28-dot display and a little wider on bigger ones (see
``scaling.py``).
"""

import math
from typing import override

import numpy as np

from flipdisc.gfx import draw

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Unit cube vertices centered at origin
_VERTICES = np.array(
    [
        [-1, -1, -1],
        [+1, -1, -1],
        [+1, +1, -1],
        [-1, +1, -1],
        [-1, -1, +1],
        [+1, -1, +1],
        [+1, +1, +1],
        [-1, +1, +1],
    ],
    dtype=np.float64,
)

# 12 edges as pairs of vertex indices
_EDGES = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 0),  # back face
    (4, 5),
    (5, 6),
    (6, 7),
    (7, 4),  # front face
    (0, 4),
    (1, 5),
    (2, 6),
    (3, 7),  # connecting edges
]


def _rotation_matrix(angle_x: float, angle_y: float, angle_z: float) -> np.ndarray:
    """Build a combined rotation matrix from Euler angles (radians)."""
    cx, sx = math.cos(angle_x), math.sin(angle_x)
    cy, sy = math.cos(angle_y), math.sin(angle_y)
    cz, sz = math.cos(angle_z), math.sin(angle_z)

    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

    return rz @ ry @ rx


@register_animation("wireframe_cube")
class WireframeCube(Animation):
    """Rotating 3D wireframe cube, oldschool demoscene style."""

    PARAMS = (
        # Cube size as a fraction of the display
        Param("size", float, 0.35, min=0.1, max=0.5, step=0.05),
        Param("rotation_speed", float, 0.35, min=-5, max=5, step=0.05, unit="rad/s"),
        # Rotation weight per axis
        Param("axis_x", float, 1.0, min=-2, max=2, step=0.1),
        Param("axis_y", float, 0.7, min=-2, max=2, step=0.1),
        Param("axis_z", float, 0.3, min=-2, max=2, step=0.1),
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)

        for name in ("size", "rotation_speed", "axis_x", "axis_y", "axis_z"):
            setattr(self, name, self.params[name])

        self.angle = 0.0
        self._line_width = self.scale.line()

    @override
    def on_configure(self, **params):
        # Every parameter maps straight onto the attribute of the same name
        for name, value in params.items():
            setattr(self, name, value)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self.angle += self.rotation_speed * dt

    @override
    def render_gray(self) -> np.ndarray:
        # Rotate vertices
        rot = _rotation_matrix(
            self.angle * self.axis_x,
            self.angle * self.axis_y,
            self.angle * self.axis_z,
        )
        rotated = _VERTICES @ rot.T

        # Weak perspective projection (z pushes things slightly smaller/larger)
        extent = self.scale.short_side * self.size
        centre = np.array([self.width / 2, self.height / 2])
        depth_scale = 6.0  # distance from camera; larger = flatter

        factor = depth_scale / (depth_scale + rotated[:, 2])  # (8,) broadcast
        projected = centre + rotated[:, :2] * (extent * factor)[:, None]

        frame = np.zeros((self.height, self.width), dtype=np.float32)
        for i0, i1 in _EDGES:
            draw.line(frame, projected[i0], projected[i1], self._line_width)
        return frame
