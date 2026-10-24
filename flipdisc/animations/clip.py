"""Clip playback animation — plays a pre-rendered GIF frame sequence."""

import math
from typing import override

import numpy as np
from PIL import Image

from flipdisc.clips.loader import ClipData, list_clips, load_clip

from .base import Animation, register_animation
from .params import Param


def _blit_fit(canvas: np.ndarray, src: np.ndarray, mode: str) -> None:
    """Blit ``src`` onto ``canvas`` using the specified fit mode.

    Args:
        canvas: Destination float32 array (H, W).
        src: Source float32 array (Hs, Ws).
        mode: "center" (pad/crop), "stretch" (nearest-neighbor), or "tile".
    """
    ch, cw = canvas.shape
    sh, sw = src.shape

    if mode == "center":
        dst_y = max(0, (ch - sh) // 2)
        dst_x = max(0, (cw - sw) // 2)
        src_y = max(0, (sh - ch) // 2)
        src_x = max(0, (sw - cw) // 2)
        h = min(ch - dst_y, sh - src_y)
        w = min(cw - dst_x, sw - src_x)
        if h > 0 and w > 0:
            canvas[dst_y : dst_y + h, dst_x : dst_x + w] = src[
                src_y : src_y + h, src_x : src_x + w
            ]

    elif mode == "stretch":
        y_idx = (np.arange(ch) * sh // max(ch, 1)).clip(0, sh - 1)
        x_idx = (np.arange(cw) * sw // max(cw, 1)).clip(0, sw - 1)
        canvas[:] = src[np.ix_(y_idx, x_idx)]

    elif mode == "tile":
        n_y = -(-ch // sh)  # ceiling division
        n_x = -(-cw // sw)
        canvas[:] = np.tile(src, (n_y, n_x))[:ch, :cw]


def _shrink_to_fit(clip: ClipData, width: int, height: int) -> np.ndarray:
    """Return the clip's frames shrunk to fit inside width x height.

    Keeps the aspect ratio. Each frame is box-averaged, so a cell's value is
    the share of it that was lit; frames are then averaged over
    ``clip.smoothing`` frames (wrapping around if the clip loops) and
    binarized: the brightest ``clip.coverage`` share of each frame, or cells
    more than half lit. Frames that already fit are returned unchanged.
    """
    frames = clip.frames
    n, h, w = frames.shape
    scale = min(width / w, height / h)
    if scale >= 1:
        return frames

    size = (max(1, math.floor(w * scale)), max(1, math.floor(h * scale)))
    gray = np.stack(
        [
            np.asarray(Image.fromarray(f.astype(np.float32)).resize(size, Image.BOX))
            for f in frames
        ]
    )

    r = clip.smoothing // 2
    if r > 0:
        if clip.loop:
            gray = np.mean([np.roll(gray, s, axis=0) for s in range(-r, r + 1)], 0)
        else:
            padded = np.pad(gray, ((r, r), (0, 0), (0, 0)), mode="edge")
            gray = np.mean([padded[s : s + n] for s in range(2 * r + 1)], 0)

    if clip.coverage is None:
        return gray > 0.5
    threshold = np.quantile(gray, 1 - clip.coverage, axis=(1, 2), keepdims=True)
    return gray > threshold


_FIT_MODES = ("fit", "center", "stretch", "tile")


@register_animation("clip")
class ClipAnimation(Animation):
    """Plays a pre-rendered clip (GIF) full-screen on the display.

    Configure with ``name`` (required) to select a clip from clips.toml.
    ``fit_mode`` "fit" shrinks a clip larger than the display to fit it
    (see ``_shrink_to_fit``) and centres it; the other modes play it at its
    own resolution.

    API usage::

        POST / anim / clip
        {"name": "rain", "loop": true}
    """

    PARAMS = (
        # Clip names come from clips.toml; an unknown name fails when it is loaded
        Param("name", str, None, choices=list_clips, strict=False, nullable=True),
        # None = use the values stored with the clip
        Param("fps_override", float, None, min=0.1, max=120, unit="fps", nullable=True),
        Param("loop", bool, None, nullable=True),
        Param("fit_mode", str, "fit", choices=_FIT_MODES),
    )

    def __init__(self, width: int, height: int):
        super().__init__(width, height, processing_steps=None)
        self._clip: ClipData | None = None
        # The clip's frames as they will be drawn, shrunk in "fit" mode
        self._frames: np.ndarray | None = None
        self._fps: float = 20.0
        self._loop: bool = True
        self._frame_idx: float = 0.0

    @override
    def on_configure(self, **params) -> None:
        if params.get("name") is not None:
            self._clip = load_clip(params["name"])
            self._fps = self._clip.fps
            self._loop = self._clip.loop
            self._frame_idx = 0.0
            self._completed = False
        if params.get("fps_override") is not None:
            self._fps = params["fps_override"]
        if params.get("loop") is not None:
            self._loop = params["loop"]
        if self._clip is not None and params.keys() & {"name", "fit_mode"}:
            self._frames = self._prepare_frames(self._clip)

    def _prepare_frames(self, clip: ClipData) -> np.ndarray:
        if self.params["fit_mode"] != "fit":
            return clip.frames
        return _shrink_to_fit(clip, self.width, self.height)

    @override
    def step(self, dt: float) -> None:
        self.current_time += dt
        if self._clip is None:
            return

        self._frame_idx += self._fps * dt
        n = len(self._clip.frames)

        if self._loop:
            if n > 0:
                self._frame_idx %= n
        elif self._frame_idx >= n:
            self._frame_idx = float(n - 1)
            self._completed = True

    @override
    def render_gray(self) -> np.ndarray:
        canvas = np.zeros((self.height, self.width), dtype=np.float32)
        if self._frames is None:
            return canvas

        src = self._frames[int(self._frame_idx)].astype(np.float32)
        mode = self.params["fit_mode"]
        _blit_fit(canvas, src, "center" if mode == "fit" else mode)
        return canvas

    @override
    def reset(self, seed: int | None = None) -> None:
        super().reset(seed)
        self._frame_idx = 0.0
