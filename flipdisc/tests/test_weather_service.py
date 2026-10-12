"""Tests for the weather service — WMO mapping and fetch parsing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from flipdisc.services.weather import WMO_TO_CONDITION, fetch_weather


class TestWmoMapping:
    def test_clear_sky(self):
        assert WMO_TO_CONDITION[0] == "sunny"

    def test_partly_cloudy(self):
        assert WMO_TO_CONDITION[1] == "partly_cloudy"
        assert WMO_TO_CONDITION[2] == "partly_cloudy"

    def test_overcast(self):
        assert WMO_TO_CONDITION[3] == "cloudy"

    def test_fog(self):
        assert WMO_TO_CONDITION[45] == "fog"
        assert WMO_TO_CONDITION[48] == "fog"

    def test_rain_codes(self):
        for code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
            assert WMO_TO_CONDITION[code] == "rain", f"Code {code} should be rain"

    def test_snow_codes(self):
        for code in [71, 73, 75, 77, 85, 86]:
            assert WMO_TO_CONDITION[code] == "snow", f"Code {code} should be snow"

    def test_thunderstorm_codes(self):
        for code in [95, 96, 99]:
            assert WMO_TO_CONDITION[code] == "thunderstorm", (
                f"Code {code} should be thunderstorm"
            )

    def test_all_values_are_valid_conditions(self):
        valid = {
            "sunny",
            "partly_cloudy",
            "cloudy",
            "fog",
            "rain",
            "snow",
            "thunderstorm",
        }
        for code, cond in WMO_TO_CONDITION.items():
            assert cond in valid, f"Code {code} maps to unknown condition {cond!r}"


class TestFetchWeather:
    def _make_mock_response(
        self, temp: float, weathercode: int, is_day: int = 1
    ) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "current_weather": {
                "temperature": temp,
                "weathercode": weathercode,
                "is_day": is_day,
            }
        }
        return resp

    def _run(self, coro):
        return asyncio.run(coro)

    def test_fetch_sunny(self):
        mock_resp = self._make_mock_response(72.5, 0)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            data = self._run(fetch_weather(37.77, -122.41, unit="F"))

        assert data.temp == 72.5
        assert data.condition == "sunny"
        assert data.unit == "F"

    def test_fetch_unknown_wmo_falls_back_to_cloudy(self):
        mock_resp = self._make_mock_response(15.0, 999)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            data = self._run(fetch_weather(0.0, 0.0, unit="C"))

        assert data.condition == "cloudy"
        assert data.unit == "C"

    def test_fetch_uses_correct_temp_unit_param(self):
        mock_resp = self._make_mock_response(22.0, 3)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            self._run(fetch_weather(48.0, 16.0, unit="C"))

        call_kwargs = mock_client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["temperature_unit"] == "celsius"

    def test_fetch_fahrenheit_unit_param(self):
        mock_resp = self._make_mock_response(72.0, 0)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            self._run(fetch_weather(37.77, -122.41, unit="F"))

        call_kwargs = mock_client.get.call_args
        params = call_kwargs[1]["params"]
        assert params["temperature_unit"] == "fahrenheit"

    def test_clear_night_includes_moon_phase(self):
        mock_resp = self._make_mock_response(55.0, 0, is_day=0)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            data = self._run(fetch_weather(37.77, -122.41, unit="F"))

        assert data.condition == "moon"
        assert data.moon_phase is not None
        assert 0.0 <= data.moon_phase < 1.0

    def test_daytime_has_no_moon_phase(self):
        mock_resp = self._make_mock_response(72.0, 0, is_day=1)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            data = self._run(fetch_weather(37.77, -122.41, unit="F"))

        assert data.condition == "sunny"
        assert data.moon_phase is None

    def test_fetch_includes_wmo_code(self):
        mock_resp = self._make_mock_response(55.0, 65)
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("flipdisc.services.weather.httpx.AsyncClient", return_value=mock_cm):
            data = self._run(fetch_weather(37.77, -122.41, unit="F"))

        assert data.wmo_code == 65
        assert data.condition == "rain"
