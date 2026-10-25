"""Tests for the 1-bit drawing shapes."""

import math
from itertools import pairwise

import numpy as np
import pytest
from scipy import ndimage

from flipdisc.gfx import draw


def _frame(width: int = 28, height: int = 28) -> np.ndarray:
    return np.zeros((height, width), dtype=bool)


@pytest.mark.parametrize("angle", np.linspace(0, math.pi, 13))
def test_a_one_dot_line_lights_one_dot_per_step(angle):
    frame = _frame(40, 40)
    centre = np.array([20.3, 19.8])
    reach = 15 * np.array([math.cos(angle), math.sin(angle)])
    draw.line(frame, centre - reach, centre + reach)
    # One dot in every column it crosses (or row, if it's nearer vertical)
    counts = frame.sum(axis=0 if abs(reach[0]) >= abs(reach[1]) else 1)
    assert set(counts[counts > 0].tolist()) == {1}


def test_a_line_along_a_pixel_boundary_does_not_double_up():
    frame = _frame()
    draw.line(frame, (2.5, 14.0), (25.5, 14.0))
    assert frame.any(axis=1).sum() == 1


def test_a_fractional_width_doubles_up_that_fraction_of_steps():
    frame = _frame(200, 200)
    draw.line(frame, (0.5, 10.0), (199.5, 77.3), width=1.5)
    counts = frame.sum(axis=0)
    assert set(counts.tolist()) <= {1, 2}
    assert np.mean(counts == 2) == pytest.approx(0.5, abs=0.05)


def test_lines_meeting_at_a_point_join_without_a_gap():
    frame = _frame()
    corners = [(4.2, 20.7), (13.9, 3.1), (24.6, 22.4), (4.2, 20.7)]
    for start, end in pairwise(corners):
        draw.line(frame, start, end)
    _, pieces = ndimage.label(frame, structure=np.ones((3, 3)))
    assert pieces == 1


def test_shapes_are_clipped_to_the_frame():
    frame = _frame(10, 10)
    draw.line(frame, (-5.0, 5.5), (5.5, 5.5))
    draw.disc(frame, (9.5, 0.5), 2.0)
    draw.ring(frame, (0.5, 9.5), 3.0)
    draw.block(frame, (0.0, 0.0), 4)
    assert frame[5, :6].all() and not frame[5, 6:].any()
    assert frame[0, 9] and frame[0:2, 0:2].all()


def test_shapes_entirely_off_the_frame_draw_nothing():
    frame = _frame(10, 10)
    draw.line(frame, (-9.0, -3.0), (-1.0, -8.0))
    draw.disc(frame, (30.0, 4.0), 3.0)
    draw.ring(frame, (5.0, -20.0), 4.0)
    draw.block(frame, (-10.0, 5.0), 3)
    assert not frame.any()


def test_a_zero_length_line_draws_nothing():
    frame = _frame()
    draw.line(frame, (5.5, 5.5), (5.5, 5.5))
    assert not frame.any()


def test_disc_lights_every_centre_within_its_radius():
    frame = _frame()
    draw.disc(frame, (10.5, 10.5), 1.6)
    assert frame.sum() == 9 and frame[9:12, 9:12].all()


def test_ring_lights_a_band_around_its_radius():
    frame = _frame()
    draw.ring(frame, (14.5, 14.5), 8.0)
    rows, cols = np.nonzero(frame)
    offsets = np.hypot(cols + 0.5 - 14.5, rows + 0.5 - 14.5) - 8.0
    assert np.all((offsets >= -0.5) & (offsets < 0.5))
    # Centred on a dot, so it's the same after a quarter turn
    assert np.array_equal(frame[1:, 1:], np.rot90(frame[1:, 1:]))


@pytest.mark.parametrize(
    ("centre", "size", "cells"),
    [
        ((10.5, 12.5), 1, {(10, 12)}),
        ((11.0, 13.0), 2, {(10, 12), (11, 12), (10, 13), (11, 13)}),
        ((11.0, 13.0), (3, 1), {(10, 13), (11, 13), (12, 13)}),
    ],
)
def test_block_lands_on_the_dots_nearest_its_centre(centre, size, cells):
    frame = _frame()
    width, height = size if isinstance(size, tuple) else (size, None)
    draw.block(frame, centre, width, height)
    rows, cols = np.nonzero(frame)
    assert set(zip(cols.tolist(), rows.tolist(), strict=True)) == cells


def test_drawing_adds_to_what_is_there_on_float_frames():
    frame = np.zeros((10, 10), dtype=np.float32)
    frame[0, 0] = 1.0
    draw.disc(frame, (5.5, 5.5), 1.0)
    assert frame[0, 0] == 1.0 and frame[5, 5] == 1.0
    assert set(np.unique(frame).tolist()) == {0.0, 1.0}


def test_pixel_centres_are_half_a_dot_in():
    xs, ys = draw.pixel_centres(3, 2)
    assert xs.shape == ys.shape == (2, 3)
    assert xs[0].tolist() == [0.5, 1.5, 2.5] and ys[:, 0].tolist() == [0.5, 1.5]
