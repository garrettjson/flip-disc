"""Pendulum animation - classic physics simulation.

A chain of one to five arms swings from a small mount at the top centre of the
display, with a bob at the end. One arm is the classic pendulum; two or more
make a chaotic multi-pendulum whose motion never repeats. Each joint carries
an equal point mass and the arms are rigid and massless.

Every size is relative to the display's smaller dimension, so the pendulum
looks the same, and swings at the same speed, on any display.
"""

import math
from itertools import pairwise
from typing import override

import numpy as np

from .base import Animation, register_animation
from .params import Param

# Sizes are given in dots on a display whose smaller dimension is this many
# dots, and scaled to the actual display
_DESIGN_SIZE = 28

_MOUNT_ROWS = 2
_MOUNT_COLUMNS = 3
# A bob of radius 1.6 covers 7 to 12 dots as it moves, staying about 3x3; at
# 1.5 it would shrink to 2x2 between pixels
_BOB_RADIUS = 1.6
_ROD_WIDTH = 1.0

# How many metres the smaller display dimension spans; sets how fast the
# swing looks (the default length, 0.8 of the display, is 2 m: a 2.8 s period)
_DISPLAY_SIZE_M = 2.5

# Longest physics substep for one arm. Chaotic motion magnifies integration
# error, so the chain is integrated with RK4 in fixed short steps whatever the
# frame rate; shorter arms swing faster, so the step is divided by the number
# of arms. This holds energy drift to about 1% a minute in the worst case
# (five arms started upside down).
_SUBSTEP_PER_ARM = 0.01  # s


@register_animation("pendulum")
class Pendulum(Animation):
    """Simple and multi-arm pendulum physics simulation."""

    PARAMS = (
        Param("gravity", float, 9.81, min=0.1, max=50, step=0.1, unit="m/s²"),
        Param("damping", float, 0.998, min=0.9, max=1.0, step=0.001),
        # From the pivot to the bob's centre with the chain straight, as a
        # fraction of the smaller display dimension; shared equally by the arms
        Param("length", float, 0.8, min=0.05, max=1, step=0.05),
        # Changing the number of arms restarts the swing from initial_angle
        Param("arms", int, 1, min=1, max=5, step=1),
        # Every arm starts at this angle, at rest; setting it restarts the
        # swing. Two or more arms need to start about horizontal (the
        # default) or higher to move chaotically, and then swing up over the
        # pivot and briefly off the top of the display.
        Param(
            "initial_angle", float, 1.571, min=-3.14, max=3.14, step=0.05, unit="rad"
        ),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)

        size = min(width, height)
        scale = size / _DESIGN_SIZE
        self._px_per_m = size / _DISPLAY_SIZE_M

        # Pendulum physics parameters, in pixels
        self.length = self.params["length"] * size
        self.gravity = self.params["gravity"] * self._px_per_m
        self.damping = self.params["damping"]  # Air resistance

        # Pendulum state: each arm's angle from straight down, and how fast
        # it's turning
        self.angles = np.zeros(0)
        self.velocities = np.zeros(0)
        self._restart()

        # The mount hangs from the top centre; the pivot sits at the middle
        # of its top edge, so the rod emerges from below it
        mount_column = width // 2
        half_mount = round((_MOUNT_COLUMNS - 1) / 2 * scale)
        mount_rows = max(1, round(_MOUNT_ROWS * scale))
        self._mount = (
            slice(0, mount_rows),
            slice(max(0, mount_column - half_mount), mount_column + half_mount + 1),
        )
        self.anchor_x = mount_column + 0.5
        self.anchor_y = 0.0

        # Under √½ the bob could fall between pixel centres and vanish
        self._bob_radius = max(math.sqrt(0.5), _BOB_RADIUS * scale)
        self._rod_half_width = max(0.5, _ROD_WIDTH * scale / 2)

        # Pixel centres, for drawing shapes as distance masks
        self._ys, self._xs = np.mgrid[0:height, 0:width] + 0.5

    def _restart(self) -> None:
        arms = self.params["arms"]
        self.angles = np.full(arms, self.params["initial_angle"])
        self.velocities = np.zeros(arms)
        # How much mass hangs at or below the further of joints i and j; it
        # couples the arms in the equations of motion
        below = arms - np.arange(arms)
        self._mass_below = np.minimum.outer(below, below).astype(float)

    @override
    def on_configure(self, **params):
        if "gravity" in params:
            self.gravity = params["gravity"] * self._px_per_m
        if "damping" in params:
            self.damping = params["damping"]
        if "length" in params:
            self.length = params["length"] * min(self.width, self.height)
        if "arms" in params or "initial_angle" in params:
            self._restart()

    def _accelerations(self, angles: np.ndarray, velocities: np.ndarray) -> np.ndarray:
        """Each arm's angular acceleration, from the chain's equations of
        motion (Lagrangian, equal point masses at the joints)."""
        arm_length = self.length / len(angles)
        apart = angles[:, None] - angles[None, :]
        coupling = self._mass_below * np.cos(apart)
        forces = (
            -self._mass_below.diagonal() * (self.gravity / arm_length) * np.sin(angles)
            - (self._mass_below * np.sin(apart)) @ velocities**2
        )
        accelerations = np.linalg.solve(coupling, forces)
        return accelerations - (1 - self.damping) * velocities

    @override
    def step(self, dt: float) -> None:
        """Advance pendulum physics."""
        self.current_time += dt
        substeps = math.ceil(dt * len(self.angles) / _SUBSTEP_PER_ARM)
        h = dt / substeps
        angles, velocities = self.angles, self.velocities
        for _ in range(substeps):
            # Classic RK4 on (angles, velocities)
            a1 = self._accelerations(angles, velocities)
            v2 = velocities + h / 2 * a1
            a2 = self._accelerations(angles + h / 2 * velocities, v2)
            v3 = velocities + h / 2 * a2
            a3 = self._accelerations(angles + h / 2 * v2, v3)
            v4 = velocities + h * a3
            a4 = self._accelerations(angles + h * v3, v4)
            angles = angles + h / 6 * (velocities + 2 * v2 + 2 * v3 + v4)
            velocities = velocities + h / 6 * (a1 + 2 * a2 + 2 * a3 + a4)
        self.angles, self.velocities = angles, velocities

    def _joint_positions(self) -> np.ndarray:
        """(x, y) of the pivot and of every joint down to the bob, shape
        (arms + 1, 2)."""
        arm_length = self.length / len(self.angles)
        steps = arm_length * np.stack((np.sin(self.angles), np.cos(self.angles)), 1)
        pivot = np.array([[self.anchor_x, self.anchor_y]])
        return np.concatenate((pivot, pivot + np.cumsum(steps, axis=0)))

    def _rod_mask(self, start: np.ndarray, end: np.ndarray) -> np.ndarray:
        """Pixels whose centre lies near the segment from start to end.

        The width is measured across rows (or columns, if the rod is nearer
        horizontal), so it's as many dots wide at every angle; a perpendicular
        width would draw a diagonal rod heavier.
        """
        rod_x, rod_y = end - start
        length_sq = rod_x**2 + rod_y**2
        if length_sq == 0:
            return np.zeros(self._xs.shape, dtype=bool)
        from_x, from_y = self._xs - start[0], self._ys - start[1]
        t = np.clip((from_x * rod_x + from_y * rod_y) / length_sq, 0.0, 1.0)
        reach = (
            self._rod_half_width * max(abs(rod_x), abs(rod_y)) / math.sqrt(length_sq)
        )
        return (from_x - t * rod_x) ** 2 + (from_y - t * rod_y) ** 2 <= reach**2

    @override
    def render_gray(self) -> np.ndarray:
        """Render the mount, arms, and bob as 1-bit shapes."""
        joints = self._joint_positions()
        lit = np.zeros(self._xs.shape, dtype=bool)
        for start, end in pairwise(joints):
            lit |= self._rod_mask(start, end)

        bob_x, bob_y = joints[-1]
        lit |= (self._xs - bob_x) ** 2 + (self._ys - bob_y) ** 2 <= self._bob_radius**2

        frame = lit.astype(np.float32)
        frame[self._mount] = 1.0
        return frame
