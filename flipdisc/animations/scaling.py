"""How an animation's sizes grow with the display.

Animations are designed on a display whose smaller dimension is 28 dots, and
every size is given either as a fraction of the animation's own box
(``short_side``, the smaller side of its viewport) or in dots on that design
display. Sizes in design dots follow the display, not the box, so a layer
draws with the same weight as a full-screen animation on the same display.

A bigger display gets finer detail while keeping a pixel-art look, so
different kinds of size grow at different rates (``factor`` is the display's
smaller dimension over 28):

- **Lengths** — positions, spans, distances, speeds — grow with the display
  (``factor``), so the layout and the timing look the same at any size.
- **Objects** — a pendulum bob, a ball, a splash — grow more slowly
  (``factor ** 0.75``), so a bigger display shows them with more detail
  rather than simply zoomed in.
- **Lines** grow slowest (``factor ** 0.25``) and keep a fractional width:
  1 dot at 28, 1.19 at 56, 1.46 at 126. ``gfx.draw.line`` lights every dot
  whose centre falls inside the line, so a width of 1.19 is mostly one dot
  with an occasional second.

- **Text** grows like an object, choosing among a font's drawn sizes (see
  ``flipdisc/fonts/font.py``).

Lines never get thinner than their design width, so they don't break up on a
display smaller than 28, and text never gets smaller than its design size
unless it has to, to fit. Objects can shrink, but ``dots`` never returns less
than one.

Every animation has one, as ``self.scale``.
"""

from .viewport import Viewport

DESIGN_SIZE = 28
OBJECT_EXPONENT = 0.75
LINE_EXPONENT = 0.25


class DisplayScale:
    """Converts design sizes (dots on a 28-dot display) for a viewport."""

    def __init__(self, viewport: Viewport):
        # The smaller side of the viewport's own box, for fractions of it
        self.short_side = min(viewport.width, viewport.height)
        display = viewport.display
        self.factor = min(display.width, display.height) / DESIGN_SIZE

    def length(self, design: float) -> float:
        """A position, distance, or speed: grows with the display."""
        return design * self.factor

    def object(self, design: float) -> float:
        """The size of a solid object, such as a radius."""
        return design * self.factor**OBJECT_EXPONENT

    def dots(self, design: float) -> int:
        """An object size in whole dots, never less than one."""
        return max(1, round(self.object(design)))

    def text(self, design: float) -> float:
        """A text height in dots, to pick a font size by: never below
        ``design``, where the smallest letters are already drawn."""
        return design * max(1.0, self.factor**OBJECT_EXPONENT)

    def line(self, design: float = 1.0) -> float:
        """A line width in dots, fractional and never below ``design``."""
        return design * max(1.0, self.factor**LINE_EXPONENT)
