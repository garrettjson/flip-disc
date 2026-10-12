"""Weather icon animation — internal sub-animation for WeatherAnimation.

Not registered in the public registry. Loads pixel-art weather icons from
assets/images/weather/ BMPs and renders them full-canvas. Precipitation
conditions (snow) overlay animated particle effects on top of cloud.bmp.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import ClassVar, override

import numpy as np
from skimage.io import imread

from flipdisc.gfx.postprocessing import downsample

from .base import Animation
from .params import Param
from .precipitation import (
    WMO_RAIN_PRESETS,
    WMO_THUNDER_PRESETS,
    LightningEffect,
    RainEffect,
    SnowEffect,
)

_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "images" / "weather"

# Map condition strings to BMP filenames
_CONDITION_FILES: dict[str, str] = {
    "sunny": "sun.bmp",
    "partly_cloudy": "cloud.bmp",
    "cloudy": "cloud.bmp",
    "rain": "cloud.bmp",
    "snow": "cloud.bmp",
    "thunderstorm": "cloud.bmp",
    "fog": "fog.bmp",
    "moon": "moon.bmp",
    "sunrise": "sun.bmp",
    "sunset": "sun.bmp",
}

# Conditions that use animated precipitation instead of a static BMP
_PRECIP_CONDITIONS = {"snow", "rain", "thunderstorm"}

_CONDITIONS = set(_CONDITION_FILES.keys())
_FALLBACK = "cloudy"

# Shared with WeatherAnimation, which forwards these to its icon layer.
# For the precipitation settings, None means "use the preset for the WMO code".
ICON_PARAMS = (
    # Not strict: an unrecognized condition falls back to the cloud icon
    Param("condition", str, _FALLBACK, choices=tuple(_CONDITION_FILES), strict=False),
    Param("wmo_code", int, None, min=0, max=99, nullable=True),
    Param("spawn_rate", float, None, min=0, max=20, step=0.1, unit="/s", nullable=True),
    Param(
        "fall_speed", float, None, min=0, max=40, step=0.1, unit="px/s", nullable=True
    ),
    Param("droplet_size", int, None, min=1, max=3, unit="px", nullable=True),
    Param(
        "strike_interval",
        float,
        None,
        min=0.1,
        max=7200,
        step=1,
        unit="s",
        nullable=True,
    ),
    Param("moon_phase", float, 0.5, min=0, max=1, step=0.05),
    Param("sun_progress", float, 0.5, min=0, max=1, step=0.05),
)

# Moon disc rendering constants — matches existing moon.bmp bounding box
_MOON_CENTER = (8, 21)  # (row, col)
_MOON_RADIUS = 7


_MIN_PHASE = 0.13  # minimum crescent width — readable on low-res display
_SUPERSAMPLE = 8  # render at Nx resolution then downsample for smooth edges

# Sunrise/sunset constants (derived from sun.bmp geometry: content spans rows 2–13)
_SUN_TOP_ROW = 2  # first row with content in sun.bmp
_SUN_BOTTOM_ROW = 13  # last row with content in sun.bmp
_SUN_TRAVEL = _SUN_BOTTOM_ROW - _SUN_TOP_ROW + 1  # 12 rows of vertical travel
_SUN_HORIZON_ROW = _SUN_BOTTOM_ROW + 1  # fixed horizon just below final sun position


def _render_moon(canvas: np.ndarray, phase: float) -> None:
    """Draw a procedural moon disc with phase-based shadow mask.

    Renders at _SUPERSAMPLE× internal resolution and block-averages down
    so crescent edges get sub-pixel anti-aliasing instead of jagged gaps.

    Args:
        canvas: (H, W) float32 array to draw into.
        phase: Moon phase in [0.0, 1.0). 0=new, 0.5=full.
    """
    # Clamp so even a new moon shows a thin 1px crescent
    phase = max(_MIN_PHASE, min(phase, 1.0 - _MIN_PHASE))

    cy, cx = _MOON_CENTER
    r = _MOON_RADIUS
    s = _SUPERSAMPLE

    # High-res patch covering the moon bounding box
    patch_size = 2 * r + 1  # low-res size
    hi_size = patch_size * s
    hi = np.zeros((hi_size, hi_size), dtype=np.float32)

    # High-res center and radius
    hi_r = r * s
    hi_cy = r * s  # center within the patch
    hi_cx = r * s

    terminator = math.cos(phase * 2.0 * math.pi)

    for row in range(hi_size):
        dy = row - hi_cy
        half_w_sq = hi_r * hi_r - dy * dy
        if half_w_sq < 0:
            continue
        half_w = math.sqrt(half_w_sq)

        if phase <= 0.5:
            term_x = hi_cx + terminator * half_w
        else:
            term_x = hi_cx - terminator * half_w

        for col in range(
            max(0, int(hi_cx - half_w)), min(hi_size, int(hi_cx + half_w) + 1)
        ):
            if (col - hi_cx) ** 2 + dy**2 > hi_r * hi_r:
                continue

            if phase <= 0.5:
                if col >= term_x:
                    hi[row, col] = 1.0
            elif col <= term_x:
                hi[row, col] = 1.0

    # Downsample: block-average hi-res patch to output resolution
    lo = downsample(hi, s)

    # Blit patch onto canvas, clipping to canvas bounds
    dst_y = cy - r
    dst_x = cx - r
    src_y0 = max(0, -dst_y)
    src_x0 = max(0, -dst_x)
    dst_y0 = max(0, dst_y)
    dst_x0 = max(0, dst_x)
    dst_y1 = min(canvas.shape[0], dst_y + patch_size)
    dst_x1 = min(canvas.shape[1], dst_x + patch_size)
    h = dst_y1 - dst_y0
    w = dst_x1 - dst_x0
    if h > 0 and w > 0:
        canvas[dst_y0:dst_y1, dst_x0:dst_x1] = lo[
            src_y0 : src_y0 + h, src_x0 : src_x0 + w
        ]


def _build_icons() -> dict[str, np.ndarray]:
    icons: dict[str, np.ndarray] = {}
    loaded: dict[str, np.ndarray] = {}

    for condition, filename in _CONDITION_FILES.items():
        path = _ICONS_DIR / filename
        if filename not in loaded:
            loaded[filename] = imread(str(path), as_gray=True).astype(np.float32)
        icons[condition] = loaded[filename]

    return icons


def _cloud_bounds(icon: np.ndarray) -> tuple[tuple[int, int], int]:
    """Find the horizontal extent and bottom row of the cloud in the icon.

    Returns:
        (col_min, col_max), bottom_row
    """
    # Scan from bottom up to find the lowest row with lit pixels
    for row in range(icon.shape[0] - 1, -1, -1):
        cols = np.where(icon[row] > 0.5)[0]
        if len(cols) > 0:
            return (int(cols[0]), int(cols[-1])), row
    # Fallback: full width, middle row
    return (0, icon.shape[1] - 1), icon.shape[0] // 2


class WeatherIconAnimation(Animation):
    """Displays a weather condition icon, with optional animated precipitation.

    Internal use only — not registered in the public animation registry.
    Used as a layer within WeatherAnimation.

    """

    PARAMS = ICON_PARAMS

    ICONS: ClassVar[dict[str, np.ndarray]] = _build_icons()

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=("binarize",))
        self._condition = _FALLBACK
        self._precip: SnowEffect | RainEffect | LightningEffect | None = None
        self._moon_phase: float = self.params["moon_phase"]  # 0.5 = full moon
        # 0 = below horizon, 1 = fully risen
        self._sun_progress: float = self.params["sun_progress"]

    @override
    def on_configure(self, **params) -> None:
        spawn_rate = params.get("spawn_rate")
        fall_speed = params.get("fall_speed")
        droplet_size = params.get("droplet_size")
        strike_interval = params.get("strike_interval")
        wmo_code = params.get("wmo_code")

        if "moon_phase" in params:
            self._moon_phase = params["moon_phase"]

        if "sun_progress" in params:
            self._sun_progress = params["sun_progress"]

        if "condition" not in params:
            # No condition change — just forward precip params if active
            if self._precip is not None:
                precip_params = {}
                if spawn_rate is not None:
                    precip_params["spawn_rate"] = spawn_rate
                if fall_speed is not None:
                    precip_params["fall_speed"] = fall_speed
                if droplet_size is not None:
                    precip_params["droplet_size"] = droplet_size
                if strike_interval is not None:
                    precip_params["strike_interval"] = strike_interval
                if precip_params:
                    self._precip.configure(**precip_params)
            return

        cond = params["condition"]
        self._condition = cond if cond in _CONDITIONS else _FALLBACK

        if self._condition not in _PRECIP_CONDITIONS:
            self._precip = None
            return

        icon = self.ICONS[self._condition]
        cols_range, bottom_row = _cloud_bounds(icon)

        if self._condition == "rain":
            # Look up WMO preset defaults, then let explicit params override
            preset = WMO_RAIN_PRESETS.get(wmo_code, {}) if wmo_code is not None else {}
            self._precip = RainEffect(
                cloud_cols_range=cols_range,
                spawn_y=bottom_row + 1,
                max_y=self.height - 1,
                spawn_rate=spawn_rate
                if spawn_rate is not None
                else preset.get("spawn_rate", 1.0),
                fall_speed=fall_speed
                if fall_speed is not None
                else preset.get("fall_speed", 4.67),
                droplet_size=int(droplet_size)
                if droplet_size is not None
                else preset.get("droplet_size", 2),
            )
        elif self._condition == "thunderstorm":
            preset = (
                WMO_THUNDER_PRESETS.get(wmo_code, {}) if wmo_code is not None else {}
            )
            self._precip = LightningEffect(
                cloud_cols_range=cols_range,
                spawn_y=bottom_row + 1,
                max_y=self.height - 1,
                strike_interval=float(strike_interval)
                if strike_interval is not None
                else preset.get("strike_interval", 900.0),
                text_row=self.height - 8,
                text_max_col=12,
            )
        else:
            self._precip = SnowEffect(
                cloud_cols_range=cols_range,
                spawn_y=bottom_row + 1,
                max_y=self.height - 1,
                spawn_rate=spawn_rate if spawn_rate is not None else 0.67,
                fall_speed=fall_speed if fall_speed is not None else 2.0,
            )

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self._precip is not None:
            self._precip.step(dt)

    @override
    def render_gray(self) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.float32)

        if self._condition == "moon":
            _render_moon(canvas, self._moon_phase)
        elif self._condition in ("sunrise", "sunset"):
            icon = self.ICONS[self._condition]
            ih, iw = icon.shape
            w = min(self.width, iw)
            # Shift sun down so it rises into position as progress increases
            shift = round(_SUN_TRAVEL * (1.0 - self._sun_progress))
            src_y0 = max(0, -shift)
            dst_y0 = max(0, shift)
            src_y1 = min(ih, self.height - shift)
            if src_y1 > src_y0:
                dst_y1 = dst_y0 + (src_y1 - src_y0)
                canvas[dst_y0:dst_y1, :w] = icon[src_y0:src_y1, :w]
            # Fixed horizon clips everything below the sun's final position
            if self.height > _SUN_HORIZON_ROW:
                canvas[_SUN_HORIZON_ROW:, :] = 0.0
        else:
            icon = self.ICONS[self._condition]
            ih, iw = icon.shape
            h = min(self.height, ih)
            w = min(self.width, iw)
            canvas[:h, :w] = icon[:h, :w]

        if self._precip is not None:
            self._precip.render(canvas)
        return canvas
