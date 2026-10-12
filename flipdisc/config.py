"""Configuration for flip-disc display."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import ConfigurationError


@dataclass
class SerialConfig:
    """Serial port configuration."""

    port: str = "/dev/ttyUSB0"
    baudrate: int = 9600
    timeout: float = 1.0
    mock: bool = True


@dataclass
class DisplayConfig:
    """Display configuration.

    Canvas dimensions (width/height) are always derived from the panel grid:
    width = panel_w * columns, height = panel_h * rows.
    """

    refresh_rate: float = 20.0
    buffer_duration: float = 0.5

    # Serial configuration
    serial: SerialConfig = field(default_factory=SerialConfig)

    # Panel grid configuration
    panel_w: int = 28
    panel_h: int = 7
    columns: int = 1
    rows: int = 4
    address_base: int = 1

    def __post_init__(self):
        if self.refresh_rate <= 0:
            raise ConfigurationError(
                f"Refresh rate must be positive: {self.refresh_rate}"
            )
        if self.buffer_duration <= 0:
            raise ConfigurationError(
                f"Buffer duration must be positive: {self.buffer_duration}"
            )
        if self.panel_w <= 0 or self.panel_h <= 0:
            raise ConfigurationError(
                f"Panel dimensions must be positive: {self.panel_w}x{self.panel_h}"
            )
        if self.columns <= 0 or self.rows <= 0:
            raise ConfigurationError(
                f"Panel grid must be positive: {self.columns}x{self.rows}"
            )

    @property
    def width(self) -> int:
        return self.panel_w * self.columns

    @property
    def height(self) -> int:
        return self.panel_h * self.rows


def default_config() -> DisplayConfig:
    """Return default config for development."""
    return DisplayConfig()


def load_config(config_path: str | None = None) -> DisplayConfig:
    """Load config from TOML file or return default."""
    if config_path is None:
        for path in ["config.toml", "flipdisc.toml"]:
            if Path(path).exists():
                config_path = path
                break
        else:
            return default_config()

    config_file = Path(config_path)
    if not config_file.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    try:
        with config_file.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigurationError(f"Failed to parse TOML config: {e}") from e

    return _parse_config(data)


def _parse_config(data: dict) -> DisplayConfig:
    """Parse TOML data into DisplayConfig."""
    try:
        display_section = data.get("display", {})
        serial_section = data.get("serial", {})

        # Parse panel dimensions from panel_type string
        panel_type = display_section.get("panel_type", "28x7")
        try:
            panel_w, panel_h = map(int, panel_type.split("x"))
        except ValueError as e:
            raise ConfigurationError(f"Invalid panel_type format: {panel_type}") from e

        serial_config = SerialConfig(
            port=serial_section.get("port", "/dev/ttyUSB0"),
            baudrate=serial_section.get("baudrate", 9600),
            timeout=serial_section.get("timeout", 1.0),
            mock=serial_section.get("mock", True),
        )

        return DisplayConfig(
            refresh_rate=display_section.get("refresh_rate", 20.0),
            buffer_duration=display_section.get("buffer_duration", 0.5),
            serial=serial_config,
            panel_w=panel_w,
            panel_h=panel_h,
            columns=display_section.get("columns", 1),
            rows=display_section.get("rows", 4),
            address_base=display_section.get("address_base", 1),
        )

    except KeyError as e:
        raise ConfigurationError(f"Missing required config key: {e}") from e
    except (ValueError, TypeError) as e:
        raise ConfigurationError(f"Invalid config value: {e}") from e
