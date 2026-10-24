"""Even-cadence stepping for motion that happens in whole steps.

On a low-resolution display a scrolling line, a falling particle, or a
cellular automaton moves in whole pixels (or whole generations), and every
move is a visible, audible flip. Accumulating ``rate * dt`` and moving when it
crosses an integer gives an irregular rhythm whenever the rate doesn't divide
the frame rate: 7 px/s at 20 fps moves every 3 frames, except when it moves
after 2.

``Cadence`` snaps the requested rate to the nearest one the frame rate can
play evenly — a whole number of frames per step, or a whole number of steps
per frame — and counts frames instead of accumulating time. The parameter
stays in units per second; the motion stays regular.

Use it for any whole-step motion. Continuous values (angles, physics
positions that get rasterized) should keep scaling by ``dt`` directly.
"""


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


class Cadence:
    """Counts frames and reports how many whole steps to take on each one."""

    def __init__(self) -> None:
        self._frames = 0

    def advance(self, rate: float, dt: float) -> int:
        """Advance one frame and return the number of whole steps to take.

        Args:
            rate: Requested steps per second (e.g. pixels per second).
            dt: Frame duration in seconds.
        """
        per_frame = rate * dt
        if per_frame <= 0:
            return 0
        if per_frame >= 1:
            return _round_half_up(per_frame)

        self._frames += 1
        if self._frames < _round_half_up(1 / per_frame):
            return 0
        self._frames = 0
        return 1

    def reset(self) -> None:
        self._frames = 0

    @staticmethod
    def snapped_rate(rate: float, dt: float) -> float:
        """The rate ``advance`` actually delivers for a requested rate."""
        per_frame = rate * dt
        if per_frame <= 0 or dt <= 0:
            return 0.0
        if per_frame >= 1:
            return _round_half_up(per_frame) / dt
        return 1 / (_round_half_up(1 / per_frame) * dt)
