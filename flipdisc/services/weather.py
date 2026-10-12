"""Weather data fetcher using Open-Meteo (free, no API key required).

Usage::

    from flipdisc.services.weather import fetch_weather

    data = await fetch_weather(37.77, -122.41, unit="F")
    print(data.temp, data.condition)  # e.g. 72.3, "sunny"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx

from flipdisc.services.moon_phase import moon_phase

# WMO weather interpretation codes → canonical condition strings
# https://open-meteo.com/en/docs#weathervariables
WMO_TO_CONDITION: dict[int, str] = {
    0: "sunny",
    1: "partly_cloudy",
    2: "partly_cloudy",
    3: "cloudy",
    45: "fog",
    48: "fog",
    51: "rain",
    53: "rain",
    55: "rain",
    56: "rain",
    57: "rain",
    61: "rain",
    63: "rain",
    65: "rain",
    66: "rain",
    67: "rain",
    71: "snow",
    73: "snow",
    75: "snow",
    77: "snow",
    80: "rain",
    81: "rain",
    82: "rain",
    85: "snow",
    86: "snow",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


_SUN_TRANSITION_MINUTES = 15  # ±15 min window around sunrise/sunset


@dataclass
class WeatherData:
    temp: float
    condition: str  # one of the canonical condition strings
    unit: str  # "F" or "C"
    wmo_code: int | None = None
    moon_phase: float | None = None
    sun_progress: float | None = None  # 0.0–1.0 during sunrise/sunset window


def _sun_transition_progress(
    now: datetime, event_time_str: str | None, window: int
) -> float | None:
    """Return normalized progress [0, 1] if now is within ±window of event, else None."""
    if not event_time_str:
        return None
    event = datetime.fromisoformat(event_time_str)
    diff = (now - event).total_seconds()
    if not (-window <= diff <= window):
        return None
    return max(0.0, min(1.0, (diff + window) / (2 * window)))


async def fetch_weather(
    latitude: float,
    longitude: float,
    unit: str = "F",
    timeout: float = 10.0,
) -> WeatherData:
    """Fetch current weather from Open-Meteo.

    Args:
        latitude: Location latitude.
        longitude: Location longitude.
        unit: Temperature unit — "F" (Fahrenheit) or "C" (Celsius).
        timeout: Request timeout in seconds.

    Returns:
        WeatherData with temp, condition, and unit.

    Raises:
        httpx.HTTPError: On network or HTTP failure.
        KeyError: If the API response is missing expected fields.
    """
    temp_unit_param = "fahrenheit" if unit.upper() == "F" else "celsius"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current_weather": "true",
        "temperature_unit": temp_unit_param,
        "daily": "sunrise,sunset",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(_OPEN_METEO_URL, params=params)
        response.raise_for_status()
        data = response.json()

    current = data["current_weather"]
    temp = float(current["temperature"])
    wmo_code = int(current["weathercode"])
    is_day = int(current.get("is_day", 1))
    condition = WMO_TO_CONDITION.get(wmo_code, "cloudy")

    # Use moon icon for clear-sky night (WMO 0 at night)
    phase: float | None = None
    if wmo_code == 0 and is_day == 0:
        condition = "moon"
        phase = moon_phase()

    # Compute sunrise/sunset progress
    sun_prog: float | None = None
    daily = data.get("daily", {})
    sunrise_list = daily.get("sunrise", [])
    sunset_list = daily.get("sunset", [])
    now_str = current.get("time")

    if now_str and (sunrise_list or sunset_list):
        now = datetime.fromisoformat(now_str)
        window = _SUN_TRANSITION_MINUTES * 60  # seconds

        rise = _sun_transition_progress(
            now, sunrise_list[0] if sunrise_list else None, window
        )
        if rise is not None:
            sun_prog = rise
            condition = "sunrise"
        else:
            sset = _sun_transition_progress(
                now, sunset_list[0] if sunset_list else None, window
            )
            if sset is not None:
                sun_prog = 1.0 - sset
                condition = "sunset"

    return WeatherData(
        temp=temp,
        condition=condition,
        unit=unit.upper(),
        wmo_code=wmo_code,
        moon_phase=phase,
        sun_progress=sun_prog,
    )
