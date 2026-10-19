"""Loading image files as grayscale frames."""

from pathlib import Path

import numpy as np
from PIL import Image

# Rec. 709 luma, the weights scikit-image's rgb2gray used before we dropped it
_LUMA = np.array([0.2125, 0.7154, 0.0721])


def load_gray(path: str | Path) -> np.ndarray:
    """Load an image file as a (H, W) float32 array with values in [0, 1].

    Any mode Pillow reads is accepted; transparent pixels count as white.
    """
    with Image.open(path) as img:
        rgba = img.convert("RGBA")
    flattened = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba)
    # In float64 so white sums to exactly 1.0 (float32 gives 0.99999994)
    rgb = np.asarray(flattened.convert("RGB"), dtype=np.float64) / 255.0
    return (rgb @ _LUMA).astype(np.float32)
