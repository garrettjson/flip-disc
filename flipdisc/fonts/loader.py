"""The fonts in ``assets/text/fonts.toml``, loaded by name.

Each entry is a family of sizes (``FontFamily``); its files are read the
first time it's asked for and kept.
"""

import tomllib
from functools import cache
from pathlib import Path

from .bdf import read_bdf
from .font import FontFamily

_FONTS_DIR = Path("assets/text")

# The family text is set in unless it asks for another
DEFAULT_FAMILY = "spleen"


def _config() -> dict:
    with (_FONTS_DIR / "fonts.toml").open("rb") as f:
        return tomllib.load(f)


@cache
def load_family(name: str) -> FontFamily:
    """The font family called ``name`` in ``fonts.toml``."""
    config = _config()
    if name not in config:
        raise KeyError(f"Font '{name}' not found in {_FONTS_DIR / 'fonts.toml'}")
    sizes = [read_bdf(_FONTS_DIR / path) for path in config[name]["sizes"]]
    return FontFamily(name, sizes)


def list_families() -> list[str]:
    """Names of the font families in ``fonts.toml``."""
    return list(_config())
