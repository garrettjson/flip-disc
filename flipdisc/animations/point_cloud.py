"""Spinning sphere of dots, simulated as masses on springs.

Each dot is a unit mass tied by a damped spring to an anchor point in a rigid
body. A motor spins the body about a (possibly tilted) axis, with inertia, so
speed changes ramp rather than jump. The dots are integrated in the inertial
frame, so the physics shows through:

- On start (and reset) every dot sits at the centre and springs out to the
  shell, overshooting a little before it settles.
- The springs must supply each dot's centripetal force, so a fast spin bulges
  the equator outward.
- Changing the spin speed makes the dots lag, then catch up; changing the
  shape makes them spring to their new anchors instead of jumping.

There are no forces between dots, so a step costs O(n).

Coordinates are in units of the sphere's radius: x right, y down (as on the
display), z towards the viewer. The body frame spins about its y axis; `tilt`
leans that axis's top towards the viewer, and `wobble` makes it precess
around that direction. Projection is orthographic.
"""

import math
from typing import Any, override

import numpy as np

from .base import Animation, register_animation
from .params import Param

# Spring stiffness (1/s², per unit mass). Natural frequency sqrt(60) ~ 7.7
# rad/s, comfortably above the fastest allowed spin: the equator bulges by
# spin² / (stiffness - spin²) of its radius, 18% at 3 rad/s.
_STIFFNESS = 60.0

# Fraction of critical damping. Below 1, so dots overshoot their anchor once
# or twice before settling.
_DAMPING_RATIO = 0.35

# Time constant (s) of the motor bringing the spin up to the requested speed
_SPIN_UP_TIME = 1.5

# Longest substep (s); keeps the spring integration stable at any frame rate
_MAX_SUBSTEP = 1 / 60

# The body's spin axis, before tilt and wobble
_Y = np.array([0.0, 1.0, 0.0])


def _rot_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _rot_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _latitudes(u: np.ndarray, concentration: float, at: str) -> np.ndarray:
    """Map u, uniform in [-1, 1], to latitudes crowded towards `at`.

    At concentration 0 both directions give asin(u), which spreads dots
    evenly over the surface (a sphere's height is uniform over its area).
    """
    if at == "equator":
        # Squeeze heights towards 0
        return np.arcsin(np.sign(u) * np.abs(u) ** (1.0 + concentration))
    if concentration <= 1.0:
        # Blend towards latitude-uniform, u * pi / 2
        return (1.0 - concentration) * np.arcsin(u) + concentration * (math.pi / 2) * u
    # Past latitude-uniform, push latitudes further poleward
    return (math.pi / 2) * np.sign(u) * np.abs(u) ** (1.0 / concentration)


@register_animation("point_cloud")
class PointCloud(Animation):
    """A cloud of dots on a spinning spherical shell."""

    PARAMS = (
        # Number of dots. Unset means density decides.
        Param("count", int, None, min=1, max=5000, nullable=True),
        # Dots per pixel of the sphere's on-screen disc, used when count is
        # unset, so the look holds across display sizes
        Param("density", float, 0.35, min=0.02, max=3, step=0.05),
        # Sphere radius as a fraction of the display's shorter side
        Param("size", float, 0.45, min=0.1, max=0.5, step=0.05),
        # 0 is a thin shell, 1 a solid ball
        Param("thickness", float, 0.1, min=0, max=1, step=0.05),
        # How strongly dots crowd towards concentrate_at; 0 spreads them
        # evenly over the surface. Towards the poles, the caps above 0.9
        # radius (10% of the surface) hold 29% of the dots at 1, 49% at 2 and
        # 64% at 3; towards the equator, the band within 0.1 radius of it
        # (also 10%) holds 32%, 46% and 56%.
        Param("concentration", float, 2.0, min=0, max=3, step=0.1),
        Param("concentrate_at", str, "poles", choices=("poles", "equator")),
        Param("spin_speed", float, 0.2, min=-3, max=3, step=0.05, unit="rad/s"),
        # Leans the top of the spin axis towards the viewer
        Param("tilt", float, 0.0, min=-90, max=90, step=5, unit="°"),
        # Precession: the spin axis leans this far off its tilted direction,
        # and the direction it leans in circles at wobble_speed
        Param("wobble", float, 0.0, min=0, max=45, step=1, unit="°"),
        Param("wobble_speed", float, 0.1, min=-3, max=3, step=0.05, unit="rad/s"),
        # RMS thermal wander of each dot around its anchor
        Param("jitter", float, 0.0, min=0, max=2, step=0.05, unit="px"),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._spin_rate = 0.0
        self._spin_angle = 0.0
        self._wobble_angle = 0.0
        self._init_dots()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _radius_px(self) -> float:
        return self.params["size"] * min(self.width, self.height)

    def _target_count(self) -> int:
        if self.params["count"] is not None:
            return self.params["count"]
        disc_area = math.pi * self._radius_px() ** 2
        return max(1, round(self.params["density"] * disc_area))

    def _init_dots(self) -> None:
        """Start every dot at the centre, at rest."""
        n = self._target_count()
        self._uniforms = np.random.random((n, 3))
        self._pos = np.zeros((n, 3))
        self._vel = np.zeros((n, 3))
        self._place_anchors()

    def _resize(self) -> None:
        """Match the dot count to the parameters, keeping the dots there are.
        New dots start at the centre and fly out to the shell."""
        n = self._target_count()
        old = len(self._pos)
        if n == old:
            return
        if n < old:
            self._uniforms = self._uniforms[:n]
            self._pos = self._pos[:n]
            self._vel = self._vel[:n]
        else:
            self._uniforms = np.vstack([self._uniforms, np.random.random((n - old, 3))])
            self._pos = np.vstack([self._pos, np.zeros((n - old, 3))])
            self._vel = np.vstack([self._vel, np.zeros((n - old, 3))])
        self._place_anchors()

    def _place_anchors(self) -> None:
        """Map each dot's three uniform randoms to its anchor in the body.

        The mappings are monotonic, so changing thickness or concentration
        moves each anchor a short way rather than reshuffling the cloud.
        """
        u_lat, u_lon, u_rad = self._uniforms.T

        lat = _latitudes(
            2.0 * u_lat - 1.0,
            self.params["concentration"],
            self.params["concentrate_at"],
        )
        lon = 2.0 * math.pi * u_lon

        # Volume-uniform between the inner radius and 1
        inner = (1.0 - self.params["thickness"]) ** 3
        r = np.cbrt(inner + u_rad * (1.0 - inner))

        self._anchors = np.column_stack(
            [
                r * np.cos(lat) * np.cos(lon),
                -r * np.sin(lat),
                r * np.cos(lat) * np.sin(lon),
            ]
        )

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _anchor_state(self) -> tuple[np.ndarray, np.ndarray]:
        """World positions and velocities of the anchors.

        The body's orientation is tilt @ wobble @ spin. The wobble tips the
        spin axis by `wobble` degrees in a direction that circles the tilted
        axis; with no wobble it is the identity, so wobble_speed alone
        changes nothing.
        """
        tilt = _rot_x(-math.radians(self.params["tilt"]))
        psi = self._wobble_angle
        wobble = (
            _rot_y(psi) @ _rot_x(math.radians(self.params["wobble"])) @ _rot_y(-psi)
        )
        orientation = tilt @ wobble @ _rot_y(self._spin_angle)

        # Angular velocity of tilt @ wobble @ spin, in world coordinates
        axis = wobble @ _Y
        omega = tilt @ (
            self.params["wobble_speed"] * (_Y - axis) + self._spin_rate * axis
        )

        anchors = self._anchors @ orientation.T
        return anchors, np.cross(omega, anchors)

    def _substep(self, h: float) -> None:
        # The motor eases the spin towards the requested speed
        target = self.params["spin_speed"]
        self._spin_rate += (target - self._spin_rate) * (
            1.0 - math.exp(-h / _SPIN_UP_TIME)
        )
        self._spin_angle += self._spin_rate * h
        self._wobble_angle += self.params["wobble_speed"] * h

        anchors, anchor_vel = self._anchor_state()

        # Damping acts on velocity relative to the anchor, so a dot riding
        # along with the body isn't slowed
        damping = 2.0 * _DAMPING_RATIO * math.sqrt(_STIFFNESS)
        accel = _STIFFNESS * (anchors - self._pos) + damping * (anchor_vel - self._vel)

        jitter = self.params["jitter"]
        if jitter > 0:
            # Langevin kicks sized so each dot's RMS offset per axis settles
            # at `jitter` pixels (fluctuation-dissipation)
            rms = jitter / self._radius_px()
            kick = math.sqrt(2.0 * damping * _STIFFNESS / h) * rms
            accel += np.random.normal(0.0, kick, self._pos.shape)

        # Semi-implicit Euler
        self._vel += accel * h
        self._pos += self._vel * h

    # ------------------------------------------------------------------
    # Animation interface
    # ------------------------------------------------------------------

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        substeps = max(1, math.ceil(dt / _MAX_SUBSTEP))
        for _ in range(substeps):
            self._substep(dt / substeps)

    @override
    def render_gray(self) -> np.ndarray:
        radius = self._radius_px()
        col = np.floor(self.width / 2 + self._pos[:, 0] * radius).astype(np.intp)
        row = np.floor(self.height / 2 + self._pos[:, 1] * radius).astype(np.intp)
        inside = (col >= 0) & (col < self.width) & (row >= 0) & (row < self.height)

        frame = np.zeros((self.height, self.width), dtype=np.float32)
        frame[row[inside], col[inside]] = 1.0
        return frame

    @override
    def on_configure(self, **params: Any) -> None:
        # Dots are added or removed without disturbing the rest
        if params.keys() & {"count", "density", "size"}:
            self._resize()
        # Dots spring from where they are to their new anchors
        if params.keys() & {"thickness", "concentration", "concentrate_at"}:
            self._place_anchors()

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._spin_rate = 0.0
        self._spin_angle = 0.0
        self._wobble_angle = 0.0
        self._init_dots()
