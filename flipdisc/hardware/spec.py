"""Flipdots protocol specification mapping (no I/O, no encoding helpers).

Defines enums and mapping from data size + refresh mode to command bytes.
Intended to be imported by both low-level encoders and higher-level facades
without creating circular imports.
"""

from enum import Enum
from typing import NamedTuple

# Protocol constants (frame markers and addressing)
START_BYTE = 0x80
END_BYTE = 0x8F
FLUSH_COMMAND = 0x82
BROADCAST_ADDRESS = 0xFF

# Panel geometry
PANEL_HEIGHT = 7  # All supported panels are 7 pixels tall


class DataBytes(Enum):
    BYTES_7 = 7
    BYTES_14 = 14
    BYTES_28 = 28

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.value} bytes"


class Refresh(Enum):
    INSTANT = "instant"  # Refresh=YES: show as received
    BUFFER = "buffer"  # Refresh=NO: store, show on FLUSH

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ProtocolConfig(NamedTuple):
    command_byte: int
    data_bytes: int
    supports_buffered: bool
    description: str


PROTOCOL_MAP: frozendict[tuple[DataBytes, Refresh], ProtocolConfig] = frozendict(
    {
        # 7x7 (7 data bytes): only instant
        (DataBytes.BYTES_7, Refresh.INSTANT): ProtocolConfig(
            command_byte=0x87,
            data_bytes=7,
            supports_buffered=False,
            description="7x7 instant",
        ),
        # 14x7 (14 data bytes): instant and buffered
        (DataBytes.BYTES_14, Refresh.INSTANT): ProtocolConfig(
            command_byte=0x92,
            data_bytes=14,
            supports_buffered=True,
            description="14x7 instant",
        ),
        (DataBytes.BYTES_14, Refresh.BUFFER): ProtocolConfig(
            command_byte=0x93,
            data_bytes=14,
            supports_buffered=True,
            description="14x7 buffered",
        ),
        # 28x7 (28 data bytes): instant and buffered
        (DataBytes.BYTES_28, Refresh.INSTANT): ProtocolConfig(
            command_byte=0x83,
            data_bytes=28,
            supports_buffered=True,
            description="28x7 instant",
        ),
        (DataBytes.BYTES_28, Refresh.BUFFER): ProtocolConfig(
            command_byte=0x84,
            data_bytes=28,
            supports_buffered=True,
            description="28x7 buffered",
        ),
    }
)


def get_protocol_config(data_bytes: DataBytes, refresh: Refresh) -> ProtocolConfig:
    cfg = PROTOCOL_MAP.get((data_bytes, refresh))
    if not cfg:
        raise ValueError(f"Unsupported configuration: {data_bytes} with {refresh}")
    return cfg


def data_bytes_from_panel_size(width: int, height: int) -> DataBytes:
    if width == 7 and height == 7:
        return DataBytes.BYTES_7
    if width == 14 and height == 7:
        return DataBytes.BYTES_14
    if width == 28 and height == 7:
        return DataBytes.BYTES_28
    raise ValueError(
        f"Unsupported panel size: {width}x{height}. Supported: 7x7, 14x7, 28x7"
    )


def supports_buffered_refresh(data_bytes: DataBytes) -> bool:
    return (data_bytes, Refresh.BUFFER) in PROTOCOL_MAP
