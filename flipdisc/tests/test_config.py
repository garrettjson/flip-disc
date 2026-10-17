"""Tests for TOML config parsing."""

import pytest

from flipdisc.config import DisplayConfig, _parse_config, load_config
from flipdisc.exceptions import ConfigurationError


def test_empty_file_gives_the_defaults():
    assert _parse_config({}) == DisplayConfig()


def test_only_keys_present_override_defaults():
    cfg = _parse_config(
        {"serial": {"baudrate": 57600}, "display": {"panel_type": "14x7"}}
    )
    assert cfg.serial.baudrate == 57600
    assert (cfg.panel_w, cfg.panel_h) == (14, 7)
    assert cfg.serial.port == DisplayConfig().serial.port
    assert cfg.rows == DisplayConfig().rows


def test_repo_config_loads():
    cfg = load_config("config.toml")
    assert (cfg.width, cfg.height) == (28, 28)


@pytest.mark.parametrize(
    "data",
    [
        {"display": {"panel_type": "28by7"}},
        {"display": {"refresh_rate": 0}},
    ],
)
def test_bad_values_raise(data):
    with pytest.raises(ConfigurationError):
        _parse_config(data)
