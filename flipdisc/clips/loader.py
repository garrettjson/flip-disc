"""Clip loader for pre-rendered .gif frame sequences."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

_CLIPS_CONFIG = "assets/clips/clips.toml"

_clip_cache: dict[str, ClipData] = {}


@dataclass
class ClipData:
    """Pre-rendered frame sequence loaded from a .gif file."""

    frames: np.ndarray  # (N, H, W) bool
    fps: float
    loop: bool
    width: int
    height: int
    description: str


def _load_gif(path: str, fps_override: float | None = None) -> tuple[np.ndarray, float]:
    """Load a multi-frame GIF into a bool frame array and fps.

    Args:
        path: Path to the .gif file.
        fps_override: If given, use this fps instead of deriving from frame duration.

    Returns:
        Tuple of (frames array (N, H, W) bool, fps float).
    """
    img = Image.open(path)
    duration_ms = img.info.get("duration", 50)
    fps = fps_override if fps_override is not None else 1000.0 / max(duration_ms, 1)

    frames: list[np.ndarray] = []
    try:
        while True:
            gray = np.array(img.convert("L"), dtype=np.float32) / 255.0
            frames.append(gray > 0.5)
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    return np.stack(frames), fps


def load_clip(name: str, config_path: str = _CLIPS_CONFIG) -> ClipData:
    """Load a named clip from the clips TOML config.

    Args:
        name: Clip name as defined in the TOML.
        config_path: Path to clips.toml, relative to the project root.

    Returns:
        A ClipData instance (cached after first load).
    """
    cache_key = f"{config_path}:{name}"
    if cache_key in _clip_cache:
        return _clip_cache[cache_key]

    with Path(config_path).open("rb") as f:
        config = tomllib.load(f)

    if name not in config:
        raise KeyError(f"Clip '{name}' not found in {config_path}")

    entry = config[name]
    fps_override = float(entry["fps"]) if "fps" in entry else None
    frames, fps = _load_gif(entry["path"], fps_override=fps_override)

    clip = ClipData(
        frames=frames,
        fps=fps,
        loop=bool(entry.get("loop", True)),
        width=int(entry.get("width", frames.shape[2])),
        height=int(entry.get("height", frames.shape[1])),
        description=str(entry.get("description", "")),
    )

    _clip_cache[cache_key] = clip
    return clip


def list_clips(config_path: str = _CLIPS_CONFIG) -> list[str]:
    """Return names of all clips defined in the manifest."""
    with Path(config_path).open("rb") as f:
        config = tomllib.load(f)
    return list(config.keys())
