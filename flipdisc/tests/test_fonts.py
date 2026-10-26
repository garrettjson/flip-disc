"""Tests for bitmap fonts: reading BDF, setting text, and picking a size."""

import numpy as np
import pytest

from flipdisc.exceptions import FontError
from flipdisc.fonts.bdf import read_bdf
from flipdisc.fonts.importer import subset_bdf
from flipdisc.fonts.loader import DEFAULT_FAMILY, list_families, load_family

SMALL = "assets/text/spleen/3x5.bdf"  # hand-drawn for this display
SPLEEN_5X8 = "assets/text/spleen/5x8.bdf"


def _bits(image: np.ndarray) -> list[list[int]]:
    return (image > 0.5).astype(int).tolist()


def test_a_font_has_every_printable_character_and_its_metrics():
    for path, height, advance in ((SMALL, 5, 4), (SPLEEN_5X8, 8, 5)):
        font = read_bdf(path)
        assert len(font._glyphs) == 95
        assert (font.height, font.advance, font.spacing) == (height, advance, 1)


def test_a_glyph_is_just_its_ink_placed_from_the_pen():
    font = read_bdf(SPLEEN_5X8)
    colon = font.get_glyph(":")
    assert colon.ink.shape == (4, 1)
    assert (colon.left, colon.top, colon.advance) == (2, 3, 5)
    assert font.get_glyph(" ").ink.size == 0


def test_the_small_size_has_a_descender_row():
    font = read_bdf(SMALL)
    assert (font.ascent, font.descent, font.cap_top, font.baseline) == (4, 1, 0, 4)
    assert _bits(font.render_line("y")) == [
        [0, 0, 0],
        [1, 0, 1],
        [1, 1, 1],
        [0, 0, 1],
        [1, 1, 0],
    ]


def test_a_line_is_a_letter_width_past_its_last_pen_position():
    font = read_bdf(SMALL)
    assert font.render_line("AB").shape == (5, 7)
    assert font.render_line("A").shape == (5, 3)
    assert font.render_line("").shape == (5, 0)
    # A narrow last character doesn't make the line narrower, so a clock's
    # digits stay put as they change
    assert font.measure("11") == font.measure("88") == font.measure("1!") == 7


def test_a_font_is_named_after_its_file():
    font = load_family("spleen").nearest(12)
    assert font.name == "spleen/6x12"
    assert font.scaled(2).name == "spleen/6x12 x2"


def test_an_unknown_character_is_blank():
    font = read_bdf(SMALL)
    assert font.render_line("\x80").sum() == 0


def test_render_wrapped_breaks_between_words():
    font = read_bdf(SMALL)
    assert font.render_wrapped("HI", max_width=28).shape == (5, 28)
    # "HI" and "AB" are 7 wide each: two lines, one blank row between
    assert font.render_wrapped("HI AB", max_width=8).shape == (11, 8)
    assert font.render_wrapped("HI AB", max_width=8, line_gap=3).shape == (13, 8)


def test_a_word_too_long_for_a_line_is_hyphenated():
    font = read_bdf(SMALL)
    lines = font.render_wrapped("ABCDEFGHIJKLMNOP", max_width=28)
    assert lines.shape[1] == 28
    # 6 letters and a hyphen fit 28 dots, and so do the last 4 letters:
    # ABCDEF- GHIJKL- MNOP
    assert lines.shape[0] == 3 * 6 - 1


def test_a_scaled_font_makes_every_dot_k_by_k():
    font = read_bdf(SMALL)
    big = font.scaled(3)
    assert (big.height, big.advance, big.cap_top) == (15, 12, 0)
    np.testing.assert_array_equal(
        big.render_line("7"), np.kron(font.render_line("7"), np.ones((3, 3)))
    )


def test_centre_top_centres_the_capitals():
    font = read_bdf(SPLEEN_5X8)
    # Capitals fill rows 1-6 of the line, so they sit at rows 11-16 of 28
    assert font.centre_top(28) + font.cap_top == 11


# --- Families ---


def test_the_families():
    assert list_families() == ["spleen", "x11"]
    assert DEFAULT_FAMILY in list_families()
    for name in list_families():
        family = load_family(name)
        heights = [font.height for font in family.sizes]
        assert heights == sorted(heights)
        for font in family.sizes:
            assert len(font._glyphs) == 95
            assert 0 <= font.cap_top < font.baseline <= font.height


def test_spleen_starts_with_the_hand_drawn_3x5():
    family = load_family("spleen")
    assert [font.name for font in family.sizes[:2]] == ["spleen/3x5", "spleen/5x8"]


@pytest.mark.parametrize(
    ("height", "picked"),
    [(5, 5), (7, 8), (8, 8), (11.8, 12), (21.6, 24), (9.7, 8), (9.9, 12), (1, 5)],
)
def test_nearest_picks_the_size_nearest_as_a_ratio(height, picked):
    assert load_family("spleen").nearest(height).height == picked


@pytest.mark.parametrize(("height", "picked"), [(104, 128), (90, 64), (300, 320)])
def test_past_the_largest_size_it_is_enlarged_by_whole_numbers(height, picked):
    font = load_family("spleen").nearest(height)
    assert font.height == picked
    assert font.advance == 32 * picked // 64


def test_fit_steps_down_until_it_fits():
    family = load_family("spleen")
    assert family.fit(24, lambda f: f.height <= 64).height == 24
    assert family.fit(24, lambda f: f.height <= 10).height == 8
    assert family.fit(24, lambda f: f.height <= 4) is None


def test_an_unknown_family_raises():
    with pytest.raises(KeyError, match="unknown"):
        load_family("unknown")


# --- BDF files ---

_TINY_BDF = """STARTFONT 2.1
FONT tiny
SIZE 2 72 72
FONTBOUNDINGBOX 2 2 0 0
STARTPROPERTIES 2
FONT_ASCENT 2
FONT_DESCENT 0
ENDPROPERTIES
CHARS 2
STARTCHAR A
ENCODING 65
DWIDTH 3 0
BBX 2 2 0 0
BITMAP
C0
40
ENDCHAR
STARTCHAR uni00E9
ENCODING 233
DWIDTH 3 0
BBX 2 2 0 0
BITMAP
C0
C0
ENDCHAR
ENDFONT
"""


def test_reading_a_bdf_file(tmp_path):
    path = tmp_path / "tiny.bdf"
    path.write_text(_TINY_BDF)
    font = read_bdf(path)
    assert set(font._glyphs) == {"A", " "}  # é isn't printable ASCII
    assert _bits(font.render_line("A")) == [[1, 1], [0, 1]]


def test_a_bdf_file_without_metrics_is_refused(tmp_path):
    path = tmp_path / "bad.bdf"
    path.write_text(_TINY_BDF.replace("FONT_ASCENT 2\n", ""))
    with pytest.raises(FontError, match="FONT_ASCENT"):
        read_bdf(path)


def test_the_importer_keeps_only_printable_characters():
    subset = subset_bdf(_TINY_BDF)
    assert "CHARS 1" in subset
    assert "ENCODING 65" in subset and "ENCODING 233" not in subset
    assert subset.startswith("STARTFONT 2.1\nFONT tiny") and "ENDFONT" in subset
