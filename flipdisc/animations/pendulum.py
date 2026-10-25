"""Pendulum animation - classic physics simulation.

A chain of one to five arms swings from a small mount at the top centre of the
display, with a bob at the end. One arm is the classic pendulum; two or more
make a chaotic multi-pendulum whose motion never repeats. Each joint carries
an equal point mass and the arms are rigid and massless.

The length and the swing are relative to the display's smaller dimension, so
the pendulum swings the same way on any display; the mount, bob, and rod grow
more slowly than the display (see ``scaling.py``).
"""

import math
from itertools import pairwise
from typing import override

import numpy as np

from flipdisc.gfx import draw

from .base import Animation, register_animation
from .params import Param
from .viewport import Viewport

# Sizes in dots on the 28-dot design display
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

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)

        self._px_per_m = self.scale.short_side / _DISPLAY_SIZE_M

        # Pendulum physics parameters, in pixels
        self.length = self.params["length"] * self.scale.short_side
        self.gravity = self.params["gravity"] * self._px_per_m
        self.damping = self.params["damping"]  # Air resistance

        # Pendulum state: each arm's angle from straight down, and how fast
        # it's turning
        self.angles = np.zeros(0)
        self.velocities = np.zeros(0)
        self._restart()

        # The pivot is the middle of the mount's top edge, so the rod emerges
        # from below it. It's on a dot's centre, and the mount an odd number
        # of dots wide, so both are symmetric about the middle column.
        self.anchor_x = self.width // 2 + 0.5
        self.anchor_y = 0.0
        half_mount = round(self.scale.object((_MOUNT_COLUMNS - 1) / 2))
        self._mount_size = (2 * half_mount + 1, self.scale.dots(_MOUNT_ROWS))

        # Under √½ the bob could fall between dot centres and vanish
        self._bob_radius = max(math.sqrt(0.5), self.scale.object(_BOB_RADIUS))
        self._rod_width = self.scale.line(_ROD_WIDTH)

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
            self.length = params["length"] * self.scale.short_side
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

    @override
    def render_gray(self) -> np.ndarray:
        """Render the mount, arms, and bob as 1-bit shapes."""
        frame = np.zeros((self.height, self.width), dtype=np.float32)
        joints = self._joint_positions()
        for start, end in pairwise(joints):
            draw.line(frame, start, end, self._rod_width)
        draw.disc(frame, joints[-1], self._bob_radius)
        mount_width, mount_rows = self._mount_size
        draw.block(frame, (self.anchor_x, mount_rows / 2), mount_width, mount_rows)
        return frame
