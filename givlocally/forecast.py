"""Solar generation forecasting via the forecast.solar public API.

API docs: https://forecast.solar/api/

The free tier requires no API key and allows up to 12 requests per hour.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta

FORECAST_SOLAR_BASE = "https://api.forecast.solar/estimate"


@dataclass
class DayForecast:
    date: date
    generation_kwh: float     # adjusted for system efficiency
    raw_kwh: float            # as returned by the API before efficiency


def _az_to_forecast_solar(azimuth_deg: int) -> int:
    """
    Convert our azimuth convention to forecast.solar's.

    Ours:            0/360=North, 90=East, 180=South, 270=West
    forecast.solar:  0=South, -90=East, 90=West, -180/180=North
    """
    return azimuth_deg - 180


def fetch_forecast(
    latitude: float,
    longitude: float,
    tilt_deg: int,
    azimuth_deg: int,
    capacity_kwp: float,
    efficiency: float,
    days: int = 2,
) -> list[DayForecast]:
    """
    Fetch daily solar generation forecasts from forecast.solar.

    Args:
        latitude:     Decimal degrees.
        longitude:    Decimal degrees.
        tilt_deg:     Panel tilt (0=flat, 90=vertical).
        azimuth_deg:  Panel azimuth in our convention (0/360=N, 90=E, 180=S, 270=W).
        capacity_kwp: Total installed peak capacity in kWp.
        efficiency:   System efficiency factor (0.0–1.0).
        days:         How many days of forecast to return (starting today).

    Returns:
        List of :class:`DayForecast` objects, one per day.

    Raises:
        RuntimeError: If the API call fails or returns an unexpected response.
    """
    az = _az_to_forecast_solar(azimuth_deg)
    url = f"{FORECAST_SOLAR_BASE}/{latitude}/{longitude}/{tilt_deg}/{az}/{capacity_kwp}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"forecast.solar API error {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach forecast.solar: {exc.reason}") from exc

    wh_day: dict[str, int] = data.get("result", {}).get("watt_hours_day", {})
    if not wh_day:
        raise RuntimeError("forecast.solar returned no daily data")

    results: list[DayForecast] = []
    for i in range(days):
        target = date.today() + timedelta(days=i)
        key = target.isoformat()
        raw_wh = wh_day.get(key, 0)
        raw_kwh = raw_wh / 1000
        results.append(DayForecast(
            date=target,
            generation_kwh=round(raw_kwh * efficiency, 2),
            raw_kwh=round(raw_kwh, 2),
        ))

    return results


def required_overnight_soc(
    forecast_kwh: float,
    daily_usage_kwh: float,
    battery_capacity_kwh: float,
    min_soc: int = 10,
) -> tuple[int, float]:
    """
    Calculate the SOC the battery should be charged to overnight.

    The logic: if solar tomorrow won't fully cover daily usage, the battery
    needs to make up the difference. We also keep a minimum SOC in reserve.

    Args:
        forecast_kwh:         Predicted solar generation for tomorrow (kWh).
        daily_usage_kwh:      Expected household consumption (kWh).
        battery_capacity_kwh: Usable battery capacity (kWh).
        min_soc:              Minimum SOC to keep in reserve (%).

    Returns:
        Tuple of (recommended_soc, shortfall_kwh).
    """
    shortfall_kwh = max(0.0, daily_usage_kwh - forecast_kwh)

    if battery_capacity_kwh <= 0:
        return 100, shortfall_kwh

    soc_for_shortfall = round(shortfall_kwh / battery_capacity_kwh * 100)
    recommended = min(100, max(min_soc, soc_for_shortfall))

    return recommended, shortfall_kwh
