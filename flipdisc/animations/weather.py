"""Weather animation — iOS-style weather widget for the flip-disc display.

Shows a pixel-art weather icon (top-right) and current temperature text
(bottom-left overlay). Registered as "weather".

Configure with:
    temp      — numeric temperature (e.g. 72)
    condition — one of: sunny, partly_cloudy, cloudy, rain, snow,
                thunderstorm, fog
    unit      — "F" or "C" (default "F")
"""

from typing import Any, override

import numpy as np

from .base import register_animation
from .composed import ComposedAnimation
from .params import Param
from .text import TextAnimation
from .viewport import Viewport
from .weather_icon import ICON_PARAMS, WeatherIconAnimation

# Small degree symbol: 3×3 diamond
#  x
# x x
#  x
_ICON_KEYS = tuple(p.name for p in ICON_PARAMS)

_DEGREE = np.array(
    [[0, 1, 0], [1, 0, 1], [0, 1, 0]],
    dtype=np.float32,
)


@register_animation("weather")
class WeatherAnimation(ComposedAnimation):
    """Weather widget: icon layer + temperature text overlay.

    Layout (28x28):
        - Icon: WeatherIconAnimation fills full canvas, placed top-right so the
          bottom-left region stays dark for the temperature text.
        - Temp: TextAnimation at x=1, y=height-8 (1px bottom pad), left-aligned.
          Shows the numeric value only; degree symbol + unit are blitted in
          render_gray so they sit flush against the number regardless of width.
        - Both layers blend with "add" (np.maximum).

    Example::

        POST / anim / weather
        {"temp": 72, "condition": "sunny", "unit": "F"}

        POST / animations / configure
        {"temp": 68, "condition": "cloudy"}
    """

    PARAMS = (
        Param("temp", float, None, min=-150, max=150, step=1, nullable=True),
        # Recorded but not drawn: only the number and degree symbol are shown
        Param("unit", str, "F", choices=("F", "C")),
        Param("show_degree", bool, True, label="Degree symbol"),
        # Pins the icon regardless of the condition pushed by the weather service;
        # empty = follow the service
        Param(
            "override_condition",
            str,
            "",
            choices=("", *(p for p in ICON_PARAMS[0].choices)),
            nullable=True,
        ),
        *ICON_PARAMS,
    )

    def __init__(self, viewport: Viewport):
        super().__init__(viewport)
        self._show_degree = self.params["show_degree"]
        self._override_condition: str | None = None
        icon = WeatherIconAnimation(self.viewport)
        icon.configure(condition="cloudy")
        temp = TextAnimation(self.viewport.region(self.width - 1, 7))
        temp.configure(text="--", mode="static", font="standard", align="left")
        self.compose(
            [
                (icon, {"id": "icon", "x": 0, "y": 0, "blend": "add"}),
                (temp, {"id": "temp", "x": 1, "y": self.height - 8, "blend": "add"}),
            ]
        )

    @override
    def on_configure(self, **params: Any) -> None:
        if "override_condition" in params:
            self._override_condition = params["override_condition"] or None

        icon_params = {k: params[k] for k in _ICON_KEYS if k in params}
        if icon_params or "override_condition" in params:
            if self._override_condition:
                icon_params["condition"] = self._override_condition
            self._update_layer("icon", icon_params)
        if params.get("temp") is not None:
            # Store number only — degree + unit drawn in render_gray
            self._update_layer("temp", {"text": str(int(params["temp"]))})
        if "show_degree" in params:
            self._show_degree = params["show_degree"]
        super().on_configure(**params)

    @override
    def render_gray(self) -> np.ndarray:
        canvas = super().render_gray()

        if not self._show_degree:
            return canvas

        for layer in self._layers:
            if layer.id != "temp":
                continue
            text_img = layer.anim._text_image
            if text_img is None:
                break

            h, w = canvas.shape
            text_w = text_img.shape[1]

            # Degree symbol: 1px gap after number, raised 3px to act as superscript
            dx = layer.x + text_w + 1
            dy = layer.y - 2
            for dr in range(_DEGREE.shape[0]):
                for dc in range(_DEGREE.shape[1]):
                    r, c = dy + dr, dx + dc
                    if 0 <= r < h and 0 <= c < w:
                        canvas[r, c] = max(canvas[r, c], _DEGREE[dr, dc])
            break

        return canvas
