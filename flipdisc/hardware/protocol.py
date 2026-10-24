"""Flipdots display protocol configuration and helpers.

Defines enums and a static mapping from data size + refresh mode to command bytes,
with a small facade bound to a DisplayConfig for convenient encoding.
"""

from collections.abc import Iterable, Mapping

import numpy as np

from flipdisc.config import DisplayConfig

from .formats import encode_flush as _encode_flush
from .formats import encode_panel_message as _encode_panel_message
from .spec import data_bytes_from_panel_size, supports_buffered_refresh


class ProtocolEncoder:
    """High-level encoder bound to a DisplayConfig."""

    def __init__(self, cfg: DisplayConfig):
        self.cfg = cfg
        self.panel_w = cfg.panel_w
        self.panel_h = cfg.panel_h
        self._data_bytes = data_bytes_from_panel_size(self.panel_w, self.panel_h)
        self._supports_buffered = supports_buffered_refresh(self._data_bytes)

    @property
    def supports_buffered(self) -> bool:
        return self._supports_buffered

    def encode_panel(
        self, panel_bits: np.ndarray, address: int, refresh: bool | None = None
    ) -> bytes:
        # Default behavior: 7x7 -> instant, 14/28 -> buffered
        if refresh is None:
            refresh = not self.supports_buffered
        return _encode_panel_message(panel_bits, address=address, refresh=refresh)

    def encode_batch(
        self, panels_bits: Iterable[np.ndarray], address_base: int
    ) -> bytes:
        """Encode every panel, addressed in order from address_base, then flush."""
        panels = {address_base + i: bits for i, bits in enumerate(panels_bits)}
        return self.encode_panels(panels)

    def encode_panels(self, panels: Mapping[int, np.ndarray]) -> bytes:
        """Encode one message per panel (keyed by address), then the flush.

        Buffered panels show nothing until the flush, which refreshes every
        controller on the line, so panels left out keep showing what they
        were last sent.
        """
        batch = b"".join(
            self.encode_panel(bits, address=address) for address, bits in panels.items()
        )
        if self.supports_buffered:
            batch += _encode_flush()
        return batch

    def encode_flush(self) -> bytes:
        return _encode_flush()
