"""
🟢 LIVE (keyless) — Open-Meteo connector.

Two free, no-key endpoints:
  * Forecast API   — hourly precipitation (mm) → rainfall intensity for Sentinel
                     and the FloodPredict ensemble seed.
  * Flood API      — GloFAS river-discharge ensemble percentiles (mean/max/p25/p75)
                     → a real uncertainty envelope for flood forecasting.

No API key required. Rate-limited free tier, so cache TTL is 900s (data updates
hourly) and every method degrades to ``None`` on failure so agents fall back to
their deterministic mock generation.
"""

from __future__ import annotations

from typing import Any, Optional

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class OpenMeteoConnector(BaseConnector):
    """Keyless rainfall + river-discharge ensemble connector."""

    source = DataSource.ECMWF_ENSEMBLE
    expected_cadence = "hourly"
    is_mock = False

    FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
    FLOOD_BASE = "https://flood-api.open-meteo.com/v1/flood"

    def __init__(self, **kwargs: Any) -> None:
        # Hourly data → 15-min cache is plenty; default to 900s per the plan.
        kwargs.setdefault("cache_ttl_seconds", 900)
        super().__init__(**kwargs)

    async def health_check(self) -> bool:
        try:
            await self.fetch_with_retry(
                self.FORECAST_BASE,
                params={"latitude": 27.7, "longitude": 85.3, "hourly": "precipitation",
                        "forecast_days": 1},
            )
            return True
        except Exception:
            return False

    async def fetch_latest(self, bbox: Optional[BBox] = None, **kwargs: Any) -> dict:
        """Return {rainfall, discharge} for the centre of ``bbox`` (or Kathmandu)."""
        if bbox is not None:
            c = bbox.center()
            lat, lng = c.lat, c.lng
        else:
            lat, lng = 27.7, 85.3
        return {
            "rainfall": await self.get_rainfall(lat, lng),
            "discharge": await self.get_discharge_ensemble(lat, lng),
        }

    async def get_rainfall(self, lat: float, lng: float) -> Optional[dict]:
        """Hourly precipitation forecast (mm). Returns None on failure."""
        try:
            data = await self.fetch_with_retry(
                self.FORECAST_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "hourly": "precipitation,precipitation_probability",
                    "forecast_days": 7,
                },
            )
            hourly = data.get("hourly", {})
            precip = [p for p in hourly.get("precipitation", []) if p is not None]
            return {
                "peak_mm_h": max(precip) if precip else 0.0,
                "total_72h_mm": round(sum(precip[:72]), 1),
                "series": precip[:120],
                "times": hourly.get("time", [])[:120],
            }
        except Exception:
            return None

    async def get_discharge_ensemble(self, lat: float, lng: float) -> Optional[dict]:
        """GloFAS river-discharge ensemble percentiles. Returns None on failure."""
        try:
            data = await self.fetch_with_retry(
                self.FLOOD_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "daily": ("river_discharge,river_discharge_mean,river_discharge_max,"
                              "river_discharge_p25,river_discharge_p75"),
                    "forecast_days": 30,
                },
            )
            daily = data.get("daily", {})
            return {
                "time": daily.get("time", []),
                "mean": daily.get("river_discharge_mean", []),
                "max": daily.get("river_discharge_max", []),
                "p25": daily.get("river_discharge_p25", []),
                "p75": daily.get("river_discharge_p75", []),
            }
        except Exception:
            return None
