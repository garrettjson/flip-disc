"""Tests for viewports and how sizes grow with the display."""

import pytest

from flipdisc.animations import Viewport, get_animation
from flipdisc.animations.scaling import DisplayScale
from flipdisc.exceptions import AnimationError


def _scale(width: int, height: int) -> DisplayScale:
    return DisplayScale(Viewport(width, height))


def test_the_design_display_changes_nothing():
    scale = _scale(28, 28)
    assert scale.factor == 1
    assert scale.length(5) == scale.object(5) == scale.line(5) == 5
    assert scale.dots(3) == 3


@pytest.mark.parametrize(
    ("size", "length", "obj", "line"),
    [(56, 2.0, 1.68, 1.19), (126, 4.5, 3.09, 1.46), (1024, 36.57, 14.87, 2.46)],
)
def test_objects_grow_slower_than_the_display_and_lines_slowest(
    size, length, obj, line
):
    scale = _scale(size, size)
    assert scale.length(1) == pytest.approx(length, abs=0.01)
    assert scale.object(1) == pytest.approx(obj, abs=0.01)
    assert scale.line() == pytest.approx(line, abs=0.01)


def test_the_shorter_side_decides():
    assert _scale(56, 28).factor == _scale(28, 140).factor == 1
    assert _scale(56, 28).short_side == 28


def test_a_small_display_never_thins_lines_or_loses_objects():
    scale = _scale(28, 7)
    assert scale.length(4) == 1
    assert scale.line() == 1
    assert scale.line(2) == 2
    assert scale.dots(1) == 1


def test_dots_rounds_to_whole_dots():
    assert _scale(56, 56).dots(4) == 7
    assert _scale(126, 126).dots(4) == 12


def test_a_region_is_a_box_on_the_same_display():
    display = Viewport(56, 56)
    layer = display.region(41, 7)
    assert (layer.width, layer.height) == (41, 7)
    assert display.display is display
    assert layer.display is display
    assert layer.region(10, 3).display is display
    assert repr(layer) == "Viewport(41x7 on 56x56)"


def test_a_viewport_must_have_dots():
    with pytest.raises(AnimationError, match="positive"):
        Viewport(0, 7)


def test_a_layer_sizes_dots_by_the_display_and_fractions_by_its_box():
    scale = DisplayScale(Viewport(56, 56).region(56, 14))
    assert scale.factor == 2  # line weight and object sizes as on the display
    assert scale.short_side == 14  # fractions of its own box


def test_every_animation_knows_its_viewport_and_scale():
    viewport = Viewport(126, 126).region(56, 28)
    anim = get_animation("pendulum", viewport)
    assert anim.viewport is viewport
    assert (anim.width, anim.height) == (56, 28)
    assert anim.scale.factor == 4.5 and anim.scale.short_side == 28


def test_layers_of_a_composed_animation_share_its_display():
    weather = get_animation("weather", Viewport(56, 56))
    composed = get_animation("composed", Viewport(56, 56))
    composed.configure(
        layers=[
            {"id": "p", "type": "pendulum", "x": 0, "y": 0, "width": 56, "height": 14}
        ]
    )
    for parent in (weather, composed):
        for layer in parent._layers:
            assert layer.anim.viewport.display is parent.viewport
            assert layer.anim.scale.factor == 2
