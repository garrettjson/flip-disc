"""Bitmap font loader for flip-disc text rendering."""

import tomllib
from pathlib import Path

import numpy as np
from skimage.io import imread

_FONTS_CONFIG = "assets/text/fonts.toml"


class BitmapFont:
    """Loads a bitmap font sprite sheet and renders text to pixel arrays."""

    def __init__(
        self,
        path: str = "assets/text/standard.bmp",
        ascii_start: int = 32,
        letters: int = 95,
        padding: int = 1,
        margin: int = 1,
        letter_width: int = 5,
        letter_height: int = 7,
    ):
        self.letter_width = letter_width
        self.letter_height = letter_height
        self._glyphs: dict[str, np.ndarray] = {}

        img = imread(str(Path(path)), as_gray=True).astype(np.float32)

        cell_w = letter_width + padding + margin
        cell_h = letter_height + padding + margin
        cols = (img.shape[1] + margin) // cell_w

        for i in range(letters):
            row = i // cols
            col = i % cols
            x = padding + col * cell_w
            y = padding + row * cell_h

            if y + letter_height > img.shape[0] or x + letter_width > img.shape[1]:
                glyph = np.zeros((letter_height, letter_width), dtype=np.float32)
            else:
                glyph = img[y : y + letter_height, x : x + letter_width].copy()

            char = chr(ascii_start + i)
            self._glyphs[char] = glyph

        # Ensure space glyph exists
        if " " not in self._glyphs:
            self._glyphs[" "] = np.zeros(
                (letter_height, letter_width), dtype=np.float32
            )

    def get_glyph(self, char: str) -> np.ndarray:
        """Get glyph array for a character, falling back to space."""
        return self._glyphs.get(char, self._glyphs[" "])

    def render_line(self, text: str, spacing: int = 1) -> np.ndarray:
        """Render a single line of text as a pixel array.

        Returns:
            Float32 array of shape (letter_height, N) where N depends on text length.
        """
        if not text:
            return np.zeros((self.letter_height, 0), dtype=np.float32)

        parts: list[np.ndarray] = []
        for i, ch in enumerate(text):
            if i > 0 and spacing > 0:
                parts.append(np.zeros((self.letter_height, spacing), dtype=np.float32))
            parts.append(self.get_glyph(ch))

        return (
            np.hstack(parts)
            if parts
            else np.zeros((self.letter_height, 0), dtype=np.float32)
        )

    def render_wrapped(
        self, text: str, max_width: int, spacing: int = 1, line_spacing: int = 1
    ) -> np.ndarray:
        """Render text with word wrapping into a pixel array.

        Returns:
            Float32 array of shape (M, max_width), left-aligned, zero-padded.
        """
        words = text.split(" ")
        lines: list[str] = []
        current_line = ""

        for word in words:
            # Check if word itself is too wide — hyphenate if needed
            word_width = self._measure_text(word, spacing)
            if word_width > max_width:
                # Flush current line first
                if current_line:
                    lines.append(current_line)
                    current_line = ""
                # Break word with hyphens
                lines.extend(self._hyphenate_word(word, max_width, spacing))
                continue

            test_line = current_line + " " + word if current_line else word

            test_width = self._measure_text(test_line, spacing)
            if test_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        if not lines:
            return np.zeros((self.letter_height, max_width), dtype=np.float32)

        # Render each line and stack
        rendered: list[np.ndarray] = []
        for i, line in enumerate(lines):
            if i > 0 and line_spacing > 0:
                rendered.append(np.zeros((line_spacing, max_width), dtype=np.float32))
            line_pixels = self.render_line(line, spacing)
            # Pad or clip to max_width
            row = np.zeros((self.letter_height, max_width), dtype=np.float32)
            w = min(line_pixels.shape[1], max_width)
            row[:, :w] = line_pixels[:, :w]
            rendered.append(row)

        return np.vstack(rendered)

    def _measure_text(self, text: str, spacing: int) -> int:
        """Measure pixel width of a text string."""
        if not text:
            return 0
        return len(text) * self.letter_width + (len(text) - 1) * spacing

    def _hyphenate_word(self, word: str, max_width: int, spacing: int) -> list[str]:
        """Break a word into chunks that fit within max_width, adding hyphens."""
        char_width = self.letter_width + spacing
        # Reserve space for hyphen at end of each chunk (except last)
        # Hyphen takes letter_width pixels
        max_chars_with_hyphen = (max_width + spacing) // char_width
        max_chars_with_hyphen = max(max_chars_with_hyphen, 2)

        chunks: list[str] = []
        remaining = word
        while remaining:
            if self._measure_text(remaining, spacing) <= max_width:
                chunks.append(remaining)
                break
            # Leave room for hyphen character
            split_at = max_chars_with_hyphen - 1
            split_at = max(split_at, 1)
            chunks.append(remaining[:split_at] + "-")
            remaining = remaining[split_at:]

        return chunks


def load_font(name: str, config_path: str = _FONTS_CONFIG) -> "BitmapFont":
    """Load a named font from the fonts TOML config.

    Args:
        name: Font name as defined in the TOML (e.g. "standard", "compact").
        config_path: Path to fonts.toml, relative to the project root.

    Returns:
        A configured BitmapFont instance.
    """
    with Path(config_path).open("rb") as f:
        config = tomllib.load(f)
    if name not in config:
        raise KeyError(f"Font '{name}' not found in {config_path}")
    return BitmapFont(**config[name])


def list_fonts(config_path: str = _FONTS_CONFIG) -> list[str]:
    """Return names of all fonts defined in the fonts TOML config."""
    with Path(config_path).open("rb") as f:
        return list(tomllib.load(f).keys())
