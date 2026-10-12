"""Panel mapping utilities: split full-frame bits into per-panel bit arrays.

Assumptions:
- Simple grid of identical panels laid out in row-major order, no rotation.
- Canvas frame is a boolean numpy array of shape (height, width).
"""

import numpy as np

from flipdisc.config import DisplayConfig
from flipdisc.exceptions import FrameError


def split_canvas_bits_to_panels(
    canvas_bits: np.ndarray, cfg: DisplayConfig
) -> list[np.ndarray]:
    """
    Split a canvas boolean image into per-panel boolean images.

    Returns row-major list of arrays with shape (panel_h, panel_w).
    """
    expected_shape = (cfg.height, cfg.width)
    if canvas_bits.shape != expected_shape:
        raise FrameError(
            f"Canvas shape mismatch: expected {expected_shape}, got {canvas_bits.shape}"
        )

    panels = (
        canvas_bits.reshape(cfg.rows, cfg.panel_h, cfg.columns, cfg.panel_w)
        .transpose(0, 2, 1, 3)
        .reshape(-1, cfg.panel_h, cfg.panel_w)
    )
    return list(panels)
