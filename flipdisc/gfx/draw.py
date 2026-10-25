"""Crisp 1-bit shapes, painted into a frame.

A dot belongs to a shape when its centre lies inside it; dot (column, row) has
its centre at (column + 0.5, row + 0.5), and points are (x, y) in the same
units. Coordinates are continuous, so a shape moves smoothly and keeps its
size wherever it is. A centre exactly on a shape's edge counts on one side
only (the low side in, the high side out), so a shape lined up with the pixel
grid never picks up an extra row.

Each function sets the shape's dots in ``frame`` (a bool or float array,
indexed [row, column]) and leaves the rest alone, so shapes combine by
drawing one after another. Only the dots near the shape are visited, so a
small shape costs the same on any size of display, and anything off the
frame is clipped.
"""

import math
from collections.abc import Sequence

import numpy as np

type Point = Sequence[float] | np.ndarray


def pixel_centres(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """(xs, ys) of every dot's centre, each shaped (height, width), for
    geometry that spans the whole display."""
    ys, xs = np.mgrid[0:height, 0:width] + 0.5
    return xs, ys


def _region(
    frame: np.ndarray, left: float, top: float, right: float, bottom: float
) -> tuple[tuple[slice, slice], np.ndarray, np.ndarray] | None:
    """The part of ``frame`` whose dot centres lie within the box: its index,
    and its centres as a row of xs and a column of ys. None if it's empty."""
    height, width = frame.shape
    c0, c1 = max(0, math.ceil(left - 0.5)), min(width, math.floor(right - 0.5) + 1)
    r0, r1 = max(0, math.ceil(top - 0.5)), min(height, math.floor(bottom - 0.5) + 1)
    if c0 >= c1 or r0 >= r1:
        return None
    xs = np.arange(c0, c1)[None, :] + 0.5
    ys = np.arange(r0, r1)[:, None] + 0.5
    return (slice(r0, r1), slice(c0, c1)), xs, ys


def line(frame: np.ndarray, start: Point, end: Point, width: float = 1.0) -> None:
    """A straight line from start to end.

    The line steps along its major axis (x if it's nearer horizontal, y
    otherwise) and its width is measured along the other, so it's as many
    dots wide at every angle; a perpendicular width would draw a diagonal
    line heavier. A width of 1 lights exactly one dot per step and a
    fractional width doubles up that fraction of them. Each end reaches half
    a dot past its endpoint, so lines meeting at a point join without a gap.
    """
    (x0, y0), (x1, y1) = start, end
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return
    pad = 0.5 + width / 2
    region = _region(
        frame,
        min(x0, x1) - pad,
        min(y0, y1) - pad,
        max(x0, x1) + pad,
        max(y0, y1) + pad,
    )
    if region is None:
        return
    index, xs, ys = region
    if abs(dx) >= abs(dy):
        along, across, step, slope = xs - x0, ys - y0, dx, dy / dx
    else:
        along, across, step, slope = ys - y0, xs - x0, dy, dx / dy
    # How far along the line each centre is (0 at start, 1 at end), and how
    # far across from the line at that point
    t = along / step
    offset = across - along * slope
    reach = 0.5 / abs(step)
    half = width / 2
    inside = (t >= -reach) & (t <= 1 + reach) & (offset >= -half) & (offset < half)
    frame[index][inside] = 1


def disc(frame: np.ndarray, centre: Point, radius: float) -> None:
    """A filled circle. Under a radius of √½ it can fall between centres and
    vanish."""
    cx, cy = centre
    region = _region(frame, cx - radius, cy - radius, cx + radius, cy + radius)
    if region is None:
        return
    index, xs, ys = region
    frame[index][(xs - cx) ** 2 + (ys - cy) ** 2 <= radius**2] = 1


def ring(frame: np.ndarray, centre: Point, radius: float, width: float = 1.0) -> None:
    """A circle outline ``width`` dots thick, measured along the radius and
    centred on ``radius``."""
    cx, cy = centre
    outer = radius + width / 2
    region = _region(frame, cx - outer, cy - outer, cx + outer, cy + outer)
    if region is None:
        return
    index, xs, ys = region
    offset = np.hypot(xs - cx, ys - cy) - radius
    frame[index][(offset >= -width / 2) & (offset < width / 2)] = 1


def block(frame: np.ndarray, centre: Point, width: int, height: int | None = None):
    """A ``width`` by ``height`` rectangle of whole dots (square if height is
    omitted), placed on the grid as near ``centre`` as it can be."""
    height = width if height is None else height
    cx, cy = centre
    # Round half up, so a tie always resolves the same way
    left = math.floor(cx - width / 2 + 0.5)
    top = math.floor(cy - height / 2 + 0.5)
    frame[max(0, top) : max(0, top + height), max(0, left) : max(0, left + width)] = 1
