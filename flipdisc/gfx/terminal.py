"""Terminal rendering utilities for inspecting animation frames during development."""

import numpy as np

from flipdisc.gfx.postprocessing import apply_processing_pipeline


def print_frame(
    frame: np.ndarray,
    label: str = "",
    on: str = "█",
    off: str = "·",
    threshold: float = 0.5,
) -> None:
    """Print a single frame to the terminal as ASCII art.

    Accepts bool arrays (from binarize) or float [0,1] arrays (from render_gray).
    Float arrays are thresholded at `threshold` before rendering.

    Args:
        frame:     2D numpy array, shape (height, width).
        label:     Optional label printed above the frame.
        on:        Character for lit pixels.
        off:       Character for dark pixels.
        threshold: Binarization cutoff for float frames.
    """
    if frame.ndim != 2:
        raise ValueError(f"Expected 2D frame, got shape {frame.shape}")

    h, w = frame.shape

    bits = frame if np.issubdtype(frame.dtype, np.bool_) else frame >= threshold

    border = "─" * w
    print(f"{label}  [{w}×{h}]" if label else f"[{w}×{h}]")
    print(f"┌{border}┐")
    for row in bits:
        print("│" + "".join(on if px else off for px in row) + "│")
    print(f"└{border}┘")


def print_animation_frames(
    animation,
    n: int = 3,
    dt: float = 1 / 10,
    apply_processing: bool = True,
    **frame_kwargs,
) -> None:
    """Step an animation and print n frames to the terminal.

    Calls animation.step(dt) then animation.render_gray() for each frame,
    optionally running the animation's own processing pipeline (e.g. binarize)
    before printing.

    Args:
        animation:         Any Animation subclass instance.
        n:                 Number of frames to render.
        dt:                Time step per frame in seconds.
        apply_processing:  If True, run animation.processing_steps on each frame.
        **frame_kwargs:    Forwarded to print_frame (on, off, threshold).
    """
    for i in range(n):
        animation.step(dt)
        frame = animation.render_gray()
        if apply_processing:
            frame = apply_processing_pipeline(frame, animation.processing_steps)
        print_frame(frame, label=f"Frame {i + 1}/{n}", **frame_kwargs)
