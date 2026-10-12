"""Post-processing functions for animation frames."""

from __future__ import annotations

import numpy as np
from scipy import ndimage
from skimage import filters


def binarize(frame: np.ndarray, threshold: float = 0.5) -> np.ndarray:
    return (frame > threshold).astype(np.bool_)


def dither(frame: np.ndarray) -> np.ndarray:
    return (filters.threshold_local(frame, 3) < frame).astype(np.bool_)


def blur(frame: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    return ndimage.gaussian_filter(frame, sigma=sigma)


def sharpen(frame: np.ndarray, strength: float = 1.0) -> np.ndarray:
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]]) * strength / 9
    return ndimage.convolve(frame, kernel)


def threshold(frame: np.ndarray, low: float = 0.3, high: float = 0.7) -> np.ndarray:
    return np.select([frame < low, frame > high], [0.0, 1.0], default=frame)


def downsample(frame: np.ndarray, factor: int) -> np.ndarray:
    """Block-average a hi-res frame down by an integer factor.

    Reshapes into (H, factor, W, factor) blocks and averages, producing
    smooth grayscale anti-aliased output from binary hi-res renders.

    Args:
        frame: (H, W) array where H and W are divisible by factor.
        factor: Integer downsampling factor (e.g. 4 or 8).

    Returns:
        (H/factor, W/factor) float32 array with values in [0, 1].
    """
    if factor == 1:
        return frame
    h, w = frame.shape
    if h % factor != 0 or w % factor != 0:
        raise ValueError(
            f"Frame dimensions ({h}, {w}) must be divisible by factor {factor}"
        )
    return frame.reshape(h // factor, factor, w // factor, factor).mean(axis=(1, 3))


PROCESSING_FUNCTIONS = {
    "binarize": binarize,
    "dither": dither,
    "blur": blur,
    "sharpen": sharpen,
    "threshold": threshold,
}


def apply_processing_pipeline(
    frame: np.ndarray, steps: tuple[str, ...] | None
) -> np.ndarray:
    if steps is None:
        return frame

    processed_frame = frame
    for step_name in steps:
        if step_name not in PROCESSING_FUNCTIONS:
            raise ValueError(f"Unknown processing step: {step_name}")
        processed_frame = PROCESSING_FUNCTIONS[step_name](processed_frame)

    return processed_frame
