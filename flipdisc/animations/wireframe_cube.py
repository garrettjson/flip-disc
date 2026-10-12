"""Rotating 3D wireframe cube animation."""

import math
from typing import override

import numpy as np

from .base import register_animation
from .supersampled import SupersampledAnimation

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


def _draw_line(
    frame: np.ndarray,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    thickness: int = 1,
) -> None:
    """Draw a line with a square brush of the given thickness."""
    h, w = frame.shape
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    steps = int(max(dx, dy))
    if steps == 0:
        return

    xs = (x1 - x0) / steps
    ys = (y1 - y0) / steps

    i = np.arange(steps + 1)
    px = np.round(x0 + i * xs).astype(int)
    py = np.round(y0 + i * ys).astype(int)

    if thickness <= 1:
        valid = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        frame[py[valid], px[valid]] = 1.0
    else:
        half = thickness // 2
        for ox in range(-half, -half + thickness):
            for oy in range(-half, -half + thickness):
                qx = px + ox
                qy = py + oy
                valid = (qx >= 0) & (qx < w) & (qy >= 0) & (qy < h)
                frame[qy[valid], qx[valid]] = 1.0


@register_animation("wireframe_cube")
class WireframeCube(SupersampledAnimation):
    """Rotating 3D wireframe cube, oldschool demoscene style."""

    def __init__(self, width: int, height: int):
        super().__init__(width, height, supersample=2, processing_steps=("binarize",))

        self.size = 0.35  # cube size as fraction of display
        self.rotation_speed = 0.35  # radians per second
        self.axis_x = 1.0  # rotation weight per axis
        self.axis_y = 0.7
        self.axis_z = 0.3

        self.angle = 0.0

        # Line thickness: next odd >= supersample so edges survive downsampling
        self._thickness = self.supersample | 1

    @override
    def configure(self, **params):
        super().configure(**params)

        if "size" in params:
            self.size = max(0.1, min(0.5, float(params["size"])))
        if "rotation_speed" in params:
            self.rotation_speed = float(params["rotation_speed"])
        if "axis_x" in params:
            self.axis_x = float(params["axis_x"])
        if "axis_y" in params:
            self.axis_y = float(params["axis_y"])
        if "axis_z" in params:
            self.axis_z = float(params["axis_z"])

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        self.angle += self.rotation_speed * dt

    @override
    def render_hires(self) -> np.ndarray:
        frame = np.zeros((self.hheight, self.hwidth), dtype=np.float32)

        # Rotate vertices
        rot = _rotation_matrix(
            self.angle * self.axis_x,
            self.angle * self.axis_y,
            self.angle * self.axis_z,
        )
        rotated = _VERTICES @ rot.T

        # Weak perspective projection (z pushes things slightly smaller/larger)
        scale = min(self.hwidth, self.hheight) * self.size
        cx, cy = self.hwidth / 2, self.hheight / 2
        depth_scale = 6.0  # distance from camera; larger = flatter

        factor = depth_scale / (depth_scale + rotated[:, 2])  # (8,) broadcast
        projected = np.empty((8, 2))
        projected[:, 0] = cx + rotated[:, 0] * scale * factor
        projected[:, 1] = cy + rotated[:, 1] * scale * factor

        # Draw edges with thickness scaled to survive downsampling
        for i0, i1 in _EDGES:
            _draw_line(
                frame,
                projected[i0, 0],
                projected[i0, 1],
                projected[i1, 0],
                projected[i1, 1],
                thickness=self._thickness,
            )

        return frame
