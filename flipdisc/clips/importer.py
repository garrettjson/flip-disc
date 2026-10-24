"""Dev utilities for importing clip data into .gif format.

Not imported by the server — use from scripts or tests only.
"""

from pathlib import Path

import numpy as np
from PIL import Image

from flipdisc.gfx.images import load_gray

# Only used in annotations, so never actually loaded
lazy from flipdisc.animations.base import Animation


def import_clip_from_png_sequence(
    folder: str | Path,
    output_path: str | Path,
    fps: float = 20.0,
    threshold: float = 0.5,
) -> None:
    """Import a PNG image sequence into a .gif clip file.

    Reads all .png files in ``folder`` (sorted lexicographically), binarizes
    each frame at ``threshold``, and saves them as an animated GIF with timing
    baked in from ``fps``.

    Args:
        folder: Directory containing sorted PNG frames.
        output_path: Destination .gif path.
        fps: Frame rate to bake into the GIF (default 20.0).
        threshold: Binarization threshold in [0, 1].
    """
    folder = Path(folder)
    png_paths = sorted(folder.glob("*.png"))
    if not png_paths:
        raise ValueError(f"No .png files found in {folder}")

    frames: list[np.ndarray] = []
    for p in png_paths:
        img = load_gray(p)
        frames.append(img > threshold)

    _save_gif(frames, output_path, fps)


def create_clip_from_animation(
    anim: Animation,
    n_frames: int,
    dt: float,
    output_path: str | Path,
    fps: float | None = None,
) -> None:
    """Record a live animation to a .gif clip file.

    Steps the animation ``n_frames`` times and records each ``render_gray()``
    output, binarized at 0.5. Timing is baked into the GIF from ``fps``
    (defaults to 1/dt if not specified).

    Args:
        anim: Any Animation instance (already configured).
        n_frames: Number of frames to record.
        dt: Time step per frame in seconds.
        output_path: Destination .gif path.
        fps: Frame rate to bake into the GIF. Defaults to 1/dt.
    """
    frames: list[np.ndarray] = []
    for _ in range(n_frames):
        anim.step(dt)
        gray = anim.render_gray()
        frames.append(gray > 0.5)

    _save_gif(frames, output_path, fps if fps is not None else 1.0 / dt)


def _save_gif(frames: list[np.ndarray], output_path: str | Path, fps: float) -> None:
    """Save a list of bool (H, W) frames as an animated GIF.

    Args:
        frames: List of (H, W) bool arrays.
        output_path: Destination .gif path.
        fps: Frame rate; baked into each frame's duration field.
    """
    duration_ms = round(1000.0 / fps)
    pil_frames = [
        Image.fromarray(f.astype(np.uint8) * 255).convert("P") for f in frames
    ]
    pil_frames[0].save(
        str(output_path),
        save_all=True,
        append_images=pil_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
