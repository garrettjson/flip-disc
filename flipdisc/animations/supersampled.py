"""Supersampled animation base class for resolution-independent rendering.

Subclasses render at N× internal resolution and the base class block-averages
down, producing smooth grayscale anti-aliased output that binarizes cleanly.
"""

from abc import abstractmethod
from typing import override

import numpy as np

from flipdisc.gfx.postprocessing import downsample

from .base import Animation


class SupersampledAnimation(Animation):
    """Animation that renders at a higher internal resolution and downsamples.

    Subclasses implement render_hires() instead of render_gray(). The hi-res
    frame is block-averaged down by the supersample factor, producing grayscale
    values that flow into the normal processing pipeline (e.g. binarize).

    Args:
        width: Output width in pixels.
        height: Output height in pixels.
        supersample: Integer scaling factor (default 4).
        processing_steps: Post-processing pipeline (default: binarize).
    """

    def __init__(
        self,
        width: int,
        height: int,
        supersample: int = 4,
        processing_steps: tuple[str, ...] | None = ("binarize",),
    ):
        super().__init__(width, height, processing_steps=processing_steps)
        self.supersample = supersample
        self.hwidth = width * supersample
        self.hheight = height * supersample

    @abstractmethod
    def render_hires(self) -> np.ndarray:
        """Render at hi-res (hheight, hwidth) resolution.

        Returns:
            float32 array of shape (hheight, hwidth) with values in [0, 1].
        """

    @override
    def render_gray(self) -> np.ndarray:
        return downsample(self.render_hires(), self.supersample)
