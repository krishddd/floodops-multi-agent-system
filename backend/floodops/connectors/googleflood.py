"""
🔑 KEY-GATED — Google Flood Forecasting API connector (v5).

Source: ``https://floodforecasting.googleapis.com/v1`` — the operational API
serving the LSTM model of Nearing et al., Nature 627, 559–563 (2024), DOI
10.1038/s41586-024-07145-1 (the system behind https://g.co/floodhub). Free of
charge under CC BY 4.0; access requires a Google Cloud API key with the
"Flood Forecasting API" enabled (waitlist:
https://support.google.com/flood-hub/answer/16364306).

Activation: set ``GOOGLE_FLOOD_API_KEY`` in .env — until then ``available``
is False, ``health_check()`` fails and every method returns None (honest,
never faked). When live it provides:
  * ``get_gauges(bbox)``    — real + virtual (hybas) gauges in an area;
  * ``get_flood_status(bbox)`` — latest per-gauge flood status with severity
    EXTREME | SEVERE | ABOVE_NORMAL | NO_FLOODING | UNKNOWN, forecast trend
    (RISE/FALL/NO_CHANGE) and issue time.

Consumers treat this as the paper-model's INDEPENDENT forecast signal
(sentinel cross-validation + compound fusion) — it is never an input to the
local runoff ensemble. Coordinates WGS84. Cache TTL 1800s (statuses update a
few times a day).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox

#: Deterministic severity weight per API severity enum (used by consumers).
SEVERITY_WEIGHT = {
    "EXTREME": 0.95,
    "SEVERE": 0.8,
    "ABOVE_NORMAL": 0.5,
    "NO_FLOODING": 0.1,
    "UNKNOWN": 0.0,
}


class GoogleFloodConnector(BaseConnector):
    """Google Flood Forecasting API (the Nature-2024 model, operational)."""

    source = DataSource.GOOGLE_FLOOD
    expected_cadence = "several/day"
    is_mock = False

    API_BASE = "https://floodforecasting.googleapis.com/v1"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("cache_ttl_seconds", 1800)
        super().__init__(**kwargs)
        self._api_key = (api_key if api_key is not None
                         else os.getenv("GOOGLE_FLOOD_API_KEY", ""))

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    async def health_check(self) -> bool:
        if not self.available:
            return False
        try:
            gauges = await self.get_gauges(
                BBox(south=27.2, west=84.8, north=28.2, east=85.8)
            )
            return gauges is not None
        except Exception:
            return False

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        if bbox is None:
            bbox = BBox(south=27.2, west=84.8, north=28.2, east=85.8)
        return {"flood_status": await self.get_flood_status(bbox)}

    async def _post(self, method: str, body: dict) -> dict | None:
        """POST a JSON body to a v1 custom method, keyed. None on failure."""
        if not self.available:
            return None
        cache_key = self._cache_key(method, sorted(body.items()))
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            client = await self._get_client()
            await self._rate_limit_wait()
            resp = await client.post(
                f"{self.API_BASE}/{method}",
                params={"key": self._api_key},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            self._set_cached(cache_key, data)
            self._last_data_time = datetime.utcnow().isoformat()
            return data
        except Exception:
            return None

    @staticmethod
    def _area_body(bbox: BBox) -> dict:
        """Rectangle area filter in the API's LatLng convention (WGS84)."""
        return {
            "regionCode": "",  # unrestricted; bbox does the filtering
            "areaFilter": {
                "boundingBox": {
                    "southWest": {"latitude": bbox.south, "longitude": bbox.west},
                    "northEast": {"latitude": bbox.north, "longitude": bbox.east},
                }
            },
            "includeNonQualityVerified": True,
        }

    async def get_gauges(self, bbox: BBox) -> list[dict] | None:
        """Real + virtual gauges in the area. None on failure/no key."""
        data = await self._post("gauges:searchGaugesByArea", self._area_body(bbox))
        if data is None:
            return None
        return data.get("gauges", [])

    async def get_flood_status(self, bbox: BBox) -> list[dict] | None:
        """Latest normalized flood statuses in the area. None on failure.

        Each: ``{gauge_id, severity, severity_weight, forecast_trend,
        quality_verified, issued_time, lat, lng, source}``.
        """
        data = await self._post(
            "floodStatus:searchLatestFloodStatusByArea", self._area_body(bbox)
        )
        if data is None:
            return None
        statuses: list[dict] = []
        for s in data.get("floodStatuses", []):
            severity = str(s.get("severity", "UNKNOWN")).upper()
            loc = s.get("gaugeLocation") or {}
            statuses.append({
                "gauge_id": s.get("gaugeId", ""),
                "severity": severity,
                "severity_weight": SEVERITY_WEIGHT.get(severity, 0.0),
                "forecast_trend": s.get("forecastTrend", "NO_CHANGE"),
                "quality_verified": bool(s.get("qualityVerified", False)),
                "issued_time": s.get("issuedTime"),
                "lat": loc.get("latitude"),
                "lng": loc.get("longitude"),
                "source": "google-flood-forecasting (Nearing et al. 2024)",
            })
        return statuses
