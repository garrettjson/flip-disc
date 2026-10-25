"""Declared parameters: coercion, validation, schema, and the API boundary."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from flipdisc.animations import (
    animation_schemas,
    get_animation,
    list_animations,
    validate_params,
)
from flipdisc.animations.base import _ANIMATION_REGISTRY
from flipdisc.animations.params import Param
from flipdisc.animations.viewport import Viewport
from flipdisc.config import DisplayConfig
from flipdisc.engine.pipeline import DisplayPipeline
from flipdisc.exceptions import AnimationError
from flipdisc.web.api_server import ApiServer

# ---------------------------------------------------------------------------
# Param.coerce
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("param", "value", "expected"),
    [
        (Param("x", float), 3, 3.0),
        (Param("x", float), "2.5", 2.5),
        (Param("x", int), 4.0, 4),
        (Param("x", int), "7", 7),
        (Param("x", bool), True, True),
        (Param("x", bool), "false", False),
        (Param("x", bool), 1, True),
        (Param("x", str), "hi", "hi"),
        (Param("x", float, nullable=True), None, None),
        (Param("x", str, choices=("a", "b")), "b", "b"),
        (Param("x", str, choices=("a", "b"), strict=False), "zzz", "zzz"),
        (Param("x", list), [1, 2], [1, 2]),
    ],
)
def test_coerce_accepts(param, value, expected):
    result = param.coerce(value)
    assert result == expected
    assert type(result) is type(expected)


@pytest.mark.parametrize(
    ("param", "value"),
    [
        (Param("x", float), "abc"),
        (Param("x", float), True),
        (Param("x", float), float("nan")),
        (Param("x", float), [1]),
        (Param("x", int), 2.5),
        (Param("x", bool), "maybe"),
        (Param("x", bool), 2),
        (Param("x", str), 5),
        (Param("x", float), None),
        (Param("x", float, min=0), -0.1),
        (Param("x", float, max=1), 1.1),
        (Param("x", str, choices=("a", "b")), "c"),
        (Param("x", list), "not a list"),
    ],
)
def test_coerce_rejects(param, value):
    with pytest.raises(AnimationError, match="'x'"):
        param.coerce(value)


def test_choices_can_come_from_a_callable():
    param = Param("font", str, choices=lambda: ["a", "b"])
    assert param.coerce("a") == "a"
    assert param.to_schema()["choices"] == ["a", "b"]
    with pytest.raises(AnimationError):
        param.coerce("c")


# ---------------------------------------------------------------------------
# Every registered animation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list_animations())
def test_declared_defaults_are_valid_and_applied(name):
    cls = _ANIMATION_REGISTRY[name]
    defaults = {p.name: p.default for p in cls.PARAMS}

    # Defaults satisfy their own declarations
    assert validate_params(name, defaults) == defaults

    # A new instance starts from them, and re-applying them is accepted
    anim = get_animation(name, Viewport(28, 28))
    assert anim.params == defaults
    anim.configure(**{k: v for k, v in defaults.items() if v is not None})
    anim.step(1 / 20)
    assert anim.render_gray().shape == (28, 28)


def test_schemas_are_json_serializable_and_complete():
    schemas = animation_schemas()
    assert set(schemas) == set(list_animations())
    json.dumps(schemas)
    for params in schemas.values():
        for param in params:
            assert {"name", "type", "default", "label"} <= set(param)


def test_unknown_parameter_is_rejected_with_the_valid_names():
    with pytest.raises(AnimationError, match="rotation_speed"):
        validate_params("wireframe_cube", {"rotation_sped": 1.0})


def test_configure_on_an_instance_validates_and_coerces():
    anim = get_animation("wireframe_cube", Viewport(28, 28))
    anim.configure(rotation_speed="2")
    assert anim.rotation_speed == 2.0
    assert anim.params["rotation_speed"] == 2.0
    with pytest.raises(AnimationError):
        anim.configure(size=9)
    assert anim.size == 0.35  # unchanged by the rejected call


def test_composed_validates_layer_specs_but_passes_dotted_keys_through():
    layers = [{"id": "t", "type": "text", "params": {"text": "HI"}}]
    clean = validate_params("composed", {"layers": layers, "layer.t.text": "YO"})
    assert clean["layer.t.text"] == "YO"

    bad_type = [{"id": "t", "type": "no_such_animation"}]
    with pytest.raises(AnimationError, match="Unknown animation"):
        validate_params("composed", {"layers": bad_type})

    bad_param = [{"id": "t", "type": "text", "params": {"mode": "sideways"}}]
    with pytest.raises(AnimationError, match="mode"):
        validate_params("composed", {"layers": bad_param})


def test_dotted_layer_keys_are_checked_against_the_layer_when_applied():
    anim = get_animation("weather", Viewport(28, 28))
    anim.configure(**{"layer.temp.text": "55"})
    with pytest.raises(AnimationError, match="mode"):
        anim.configure(**{"layer.temp.mode": "sideways"})
    with pytest.raises(AnimationError, match="visible"):
        anim.configure(**{"layer.icon.visible": "maybe"})


# ---------------------------------------------------------------------------
# Pipeline and API boundary
# ---------------------------------------------------------------------------


def test_pipeline_rejects_invalid_params_before_handoff():
    async def run():
        pipeline = DisplayPipeline(DisplayConfig(buffer_duration=0.1))
        with pytest.raises(AnimationError):
            await pipeline.start("wireframe_cube", {"size": 9})
        assert pipeline.get_status().running is False

        await pipeline.start("wireframe_cube", {"size": 0.4})
        await pipeline.play()
        with pytest.raises(AnimationError):
            await pipeline.set_animation("text", {"mode": "sideways"})
        with pytest.raises(AnimationError):
            await pipeline.configure_animation({"size": "big"})
        await asyncio.sleep(0.3)

        st = pipeline.get_status()
        assert st.animation == "wireframe_cube"
        assert st.last_error is None  # nothing bad ever reached the generator
        await pipeline.stop()

    asyncio.run(run())


def _client() -> TestClient:
    cfg = DisplayConfig(buffer_duration=0.1)
    return TestClient(ApiServer(cfg, DisplayPipeline(cfg)).app)


def test_api_serves_the_schema():
    data = _client().get("/animations").json()
    assert "text" in data["animations"]
    text = {p["name"]: p for p in data["params"]["text"]}
    assert text["mode"]["choices"] == [
        "static",
        "scroll_left",
        "scroll_up",
        "scroll_down",
    ]
    assert "standard" in text["font"]["choices"]
    assert text["speed"]["unit"] == "px/s"


@pytest.mark.parametrize(
    ("name", "body", "fragment"),
    [
        ("wireframe_cube", {"size": 9}, "at most 0.5"),
        ("wireframe_cube", {"rotation_sped": 1}, "Unknown parameter"),
        ("text", {"mode": "sideways"}, "must be one of"),
        ("weather", {"temp": "warm"}, "must be a number"),
    ],
)
def test_api_returns_400_for_invalid_params(name, body, fragment):
    res = _client().post(f"/anim/{name}", json=body)
    assert res.status_code == 400
    assert fragment in res.json()["detail"]
