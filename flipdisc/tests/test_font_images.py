"""The font reference images in assets/text/ match what the code draws."""

import numpy as np
import pytest
from PIL import Image

from flipdisc.tools.font_images import IMAGES, OUT_DIR, write_images


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("font_images")
    write_images(out)
    return out


def _pixels(path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


@pytest.mark.parametrize("name", IMAGES)
def test_the_checked_in_image_is_up_to_date(generated, name):
    fresh, checked_in = _pixels(generated / name), _pixels(OUT_DIR / name)
    stale = fresh.shape != checked_in.shape or not np.array_equal(fresh, checked_in)
    assert not stale, (
        f"{OUT_DIR / name} is out of date; regenerate it with "
        "`uv run python -m flipdisc.tools.font_images`"
    )


def test_the_images_use_only_the_panel_colours(generated):
    for name in IMAGES:
        with Image.open(generated / name) as image:
            colours = {rgb for _, rgb in image.convert("RGB").getcolors()}
        assert colours == {(0, 0, 0), (40, 40, 40), (255, 255, 255)}
