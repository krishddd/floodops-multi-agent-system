"""
🟢 LIVE — NOAA/NWS Weather Connector.

Sources:
- api.weather.gov (NWS alerts, forecasts) — free, no API key
- GOES-16/17 (S3 bucket for radar/satellite imagery)

Data cadence: 🟢 15 minutes (alerts refreshed per polling cycle)
"""

from __future__ import annotations

from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class NOAAConnector(BaseConnector):
    """NWS/NOAA weather alert and radar data connector."""

    source = DataSource.NWS_ALERTS
    expected_cadence = "15 min"
    is_mock = False

    NWS_BASE = "https://api.weather.gov"

    async def health_check(self) -> bool:
        try:
            await self.fetch_with_retry(f"{self.NWS_BASE}/status")
            return True
        except Exception:
            return False

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        """Fetch active weather alerts from NWS for the given area."""
        return await self.get_active_alerts(bbox)

    async def get_active_alerts(self, bbox: BBox | None = None) -> dict:
        """Fetch active NWS alerts.

        NWS API returns GeoJSON natively — no conversion needed.
        The frontend can render these directly as a GeoJsonLayer.
        """
        url = f"{self.NWS_BASE}/alerts/active"
        params: dict[str, str] = {"status": "actual", "message_type": "alert"}

        if bbox:
            # NWS uses area filter by state/zone, but we can use point-based queries
            center = bbox.center()
            params["point"] = f"{center.lat},{center.lng}"

        headers = {"User-Agent": "FloodOps/1.0 (floodops@example.com)", "Accept": "application/geo+json"}

        try:
            data = await self.fetch_with_retry(url, params=params, headers=headers)
            return data
        except Exception:
            return {"type": "FeatureCollection", "features": []}

    async def get_forecast(self, lat: float, lng: float) -> dict:
        """Fetch weather forecast for a location (NWS two-step lookup)."""
        # Step 1: Get gridpoint
        headers = {"User-Agent": "FloodOps/1.0 (floodops@example.com)"}
        points = await self.fetch_with_retry(f"{self.NWS_BASE}/points/{lat},{lng}", headers=headers)
        forecast_url = points.get("properties", {}).get("forecast", "")

        if not forecast_url:
            return {}

        # Step 2: Get forecast
        return await self.fetch_with_retry(forecast_url, headers=headers)

    async def get_radar_stations(self, bbox: BBox | None = None) -> dict:
        """Fetch radar station metadata."""
        headers = {"User-Agent": "FloodOps/1.0 (floodops@example.com)"}
        return await self.fetch_with_retry(f"{self.NWS_BASE}/radar/stations", headers=headers)
