"""Composed animation — splits the canvas into independently-animated layers.

Primary authoring pattern: subclass ComposedAnimation, call compose() in __init__,
register with @register_animation. The API then starts it by name::

    @register_animation("weather_dashboard")
    class WeatherDashboard(ComposedAnimation):
        def __init__(self, viewport):
            super().__init__(viewport)
            temp = TextAnimation(self.viewport.region(41, 7))
            temp.configure(text="--", mode="static")
            self.compose(
                [
                    (temp, {"id": "temp", "x": 15, "y": 0}),
                ]
            )

        PARAMS = (Param("temp", int, None, nullable=True),)

        def on_configure(self, **params):
            if params.get("temp") is not None:
                self._update_layer("temp", {"text": str(params["temp"]) + "F"})
            super().on_configure(**params)


    # API: POST /anim/weather_dashboard {"temp": 72}
"""

from dataclasses import dataclass, field
from typing import Any, override

import numpy as np

from flipdisc.exceptions import AnimationError
from flipdisc.gfx.postprocessing import apply_processing_pipeline

from .base import Animation, get_animation, register_animation, validate_params
from .params import Param
from .viewport import Viewport

# Layer fields managed directly on _Layer (not forwarded to sub-animation)
_LAYER_FIELDS = frozendict(
    {
        "blend": Param("blend", str, "over", choices=("over", "add")),
        "visible": Param("visible", bool, True),
    }
)


def _validate_layer_spec(spec: Any) -> None:
    """Check one entry of a ``layers`` list: shape, animation type, and params."""
    if not isinstance(spec, dict) or "id" not in spec or "type" not in spec:
        raise AnimationError(f"Each layer needs an 'id' and a 'type', got {spec!r}")
    validate_params(str(spec["type"]), spec.get("params") or {})
    for name, param in _LAYER_FIELDS.items():
        if name in spec:
            param.coerce(spec[name])


def _blit_region(canvas: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """Blit ``src`` onto ``canvas`` at (x, y) using "over" mode, clipping to bounds."""
    ch, cw = canvas.shape
    sh, sw = src.shape
    src_y0 = max(0, -y)
    src_x0 = max(0, -x)
    dst_y0 = max(0, y)
    dst_x0 = max(0, x)
    dst_y1 = min(ch, y + sh)
    dst_x1 = min(cw, x + sw)
    src_y1 = src_y0 + (dst_y1 - dst_y0)
    src_x1 = src_x0 + (dst_x1 - dst_x0)
    if dst_y0 < dst_y1 and dst_x0 < dst_x1:
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = src[src_y0:src_y1, src_x0:src_x1]


@dataclass
class _Layer:
    id: str
    anim: Animation
    x: int
    y: int
    width: int
    height: int
    blend: str = field(default="over")  # "over" | "add"
    visible: bool = field(default=True)


@register_animation("composed")
class ComposedAnimation(Animation):
    """Combines N independently-animated layers onto a shared canvas.

    **Python authoring (primary)**: subclass and call compose() in __init__.

    **API / one-off use**: pass a ``layers`` list in configure params::

        POST / anim / composed
        {
            "layers": [
                {
                    "id": "rain",
                    "type": "clip",
                    "x": 0,
                    "y": 0,
                    "width": 14,
                    "height": 7,
                    "params": {"name": "rain", "loop": true},
                },
                {
                    "id": "temp",
                    "type": "text",
                    "x": 15,
                    "y": 0,
                    "width": 41,
                    "height": 7,
                    "params": {"text": "72F", "mode": "static", "font": "compact"},
                },
            ]
        }

    Live updates (no restart needed)::

        POST / animations / configure
        {"layer.temp.text": "68F"}
        {"layer.rain.visible": false}
        {"layer.noise.blend": "add"}
    """

    # Subclasses that wire their layers in __init__ replace this with their own
    PARAMS = (Param("layers", list, None, nullable=True),)

    def __init__(self, viewport: Viewport):
        super().__init__(viewport, processing_steps=None)
        self._layers: list[_Layer] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compose(self, layers: list[tuple[Animation, dict]]) -> None:
        """Wire up animation objects with layout params.

        This is the primary way to define a composition in Python code.
        Call it from __init__ after creating sub-animations.

        Args:
            layers: List of (animation_instance, layout_dict) pairs.
                    layout_dict keys:
                      id       — required, used for dotted-key targeting
                      x, y     — position on canvas (default 0)
                      blend    — "over" (default) or "add"
                      visible  — bool (default True)
        """
        built: list[_Layer] = []
        for anim, layout in layers:
            built.append(
                _Layer(
                    id=str(layout["id"]),
                    anim=anim,
                    x=int(layout.get("x", 0)),
                    y=int(layout.get("y", 0)),
                    width=anim.width,
                    height=anim.height,
                    blend=str(layout.get("blend", "over")),
                    visible=bool(layout.get("visible", True)),
                )
            )
        self._layers = built

    @classmethod
    @override
    def validate_params(cls, params: dict[str, Any]) -> dict[str, Any]:
        """Validate declared params; pass ``layer.<id>.<key>`` keys through.

        Dotted keys target a layer that only exists on an instance, so they
        are checked against that layer's own schema when they are applied.
        """
        dotted = {k: v for k, v in params.items() if k.startswith("layer.")}
        clean = super().validate_params(
            {k: v for k, v in params.items() if k not in dotted}
        )
        for spec in clean.get("layers") or []:
            _validate_layer_spec(spec)
        return {**clean, **dotted}

    @override
    def on_configure(self, **params: Any) -> None:
        if params.get("layers") is not None:
            self._build_layers(params["layers"])

        for key, val in params.items():
            if not key.startswith("layer."):
                continue
            parts = key.split(".", 2)
            if len(parts) != 3:
                continue
            _, layer_id, subkey = parts
            if subkey in _LAYER_FIELDS:
                self._set_layer_field(layer_id, subkey, val)
            else:
                self._update_layer(layer_id, {subkey: val})

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        for layer in self._layers:
            layer.anim.step(dt)

    @override
    def render_gray(self) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        for layer in self._layers:
            if not layer.visible:
                continue
            sub = apply_processing_pipeline(
                layer.anim.render_gray(), layer.anim.processing_steps
            ).astype(np.float32)

            # Clip destination and source regions to canvas bounds once
            dy0 = max(0, layer.y)
            dx0 = max(0, layer.x)
            dy1 = min(self.height, layer.y + layer.height)
            dx1 = min(self.width, layer.x + layer.width)
            sy0 = dy0 - layer.y
            sx0 = dx0 - layer.x
            sy1 = sy0 + (dy1 - dy0)
            sx1 = sx0 + (dx1 - dx0)

            if dy0 >= dy1 or dx0 >= dx1:
                continue

            dst = canvas[dy0:dy1, dx0:dx1]
            src = sub[sy0:sy1, sx0:sx1]
            if layer.blend == "add":
                np.maximum(dst, src, out=dst)
            else:
                dst[:] = src

        return canvas

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        for layer in self._layers:
            layer.anim.reset(seed)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_layers(self, layers_config: list[dict]) -> None:
        """Build layers from JSON/dict specs and call compose()."""
        pairs: list[tuple[Animation, dict]] = []
        for lc in layers_config:
            w = int(lc.get("width", self.width))
            h = int(lc.get("height", self.height))
            anim = get_animation(str(lc["type"]), self.viewport.region(w, h))
            if lc.get("params"):
                anim.configure(**lc["params"])
            pairs.append((anim, lc))
        self.compose(pairs)

    def _update_layer(self, layer_id: str, params: dict) -> None:
        """Forward params to a sub-animation's configure()."""
        for layer in self._layers:
            if layer.id == layer_id:
                layer.anim.configure(**params)
                return

    def _set_layer_field(self, layer_id: str, field: str, val: Any) -> None:
        """Set a layout field (blend, visible) directly on the _Layer."""
        for layer in self._layers:
            if layer.id == layer_id:
                setattr(layer, field, _LAYER_FIELDS[field].coerce(val))
                return
