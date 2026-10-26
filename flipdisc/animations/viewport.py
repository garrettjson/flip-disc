"""Where an animation draws: a box on a display.

Every animation is built for a ``Viewport``. A full-screen animation's
viewport is the display itself; a layer of a composed animation gets a
smaller region of the same display (``viewport.region(width, height)``).
The animation fills its own box, but sizes it designs in dots, such as line
widths and object sizes, follow the display, so every layer on one display
draws with the same weight (see ``scaling.py``).
"""

from flipdisc.exceptions import AnimationError


class Viewport:
    """A ``width`` x ``height`` box of dots on ``display``."""

    def __init__(self, width: int, height: int):
        if width <= 0 or height <= 0:
            raise AnimationError(
                f"Viewport dimensions must be positive: {width}x{height}"
            )
        self.width = width
        self.height = height
        # The whole display this box is part of; a new viewport is a display
        self.display = self

    def region(self, width: int, height: int) -> Viewport:
        """A ``width`` x ``height`` box on the same display, for a layer."""
        region = Viewport(width, height)
        region.display = self.display
        return region

    def __repr__(self) -> str:
        if self.display is self:
            return f"Viewport({self.width}x{self.height})"
        display = self.display
        return (
            f"Viewport({self.width}x{self.height} on {display.width}x{display.height})"
        )
