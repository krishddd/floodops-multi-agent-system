"""⚪ MOCK — GLIMS glacial lake inventory. Returns static lake data."""
from __future__ import annotations

from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource


class GLIMSConnector(BaseConnector):
    source = DataSource.GLIMS
    expected_cadence = "static"
    is_mock = True

    MOCK_LAKES = [
        {"lake_id": "GL001", "name": "Tsho Rolpa", "lat": 27.862, "lng": 86.477, "elevation_m": 4580, "area_km2": 1.54, "dam_type": "moraine", "volume_m3": 80_000_000},
        {"lake_id": "GL002", "name": "Imja Tsho", "lat": 27.899, "lng": 86.931, "elevation_m": 5010, "area_km2": 1.28, "dam_type": "moraine", "volume_m3": 61_700_000},
        {"lake_id": "GL003", "name": "Thulagi Lake", "lat": 28.490, "lng": 84.440, "elevation_m": 4060, "area_km2": 0.89, "dam_type": "moraine", "volume_m3": 35_000_000},
        {"lake_id": "GL004", "name": "Dig Tsho", "lat": 27.867, "lng": 86.583, "elevation_m": 4360, "area_km2": 0.33, "dam_type": "moraine", "volume_m3": 8_000_000},
        {"lake_id": "GL005", "name": "Barun Tsho", "lat": 27.785, "lng": 87.083, "elevation_m": 4680, "area_km2": 0.62, "dam_type": "ice", "volume_m3": 22_000_000},
    ]

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, **kwargs: Any) -> dict:
        return {"source": "glims_mock", "lakes": self.MOCK_LAKES, "count": len(self.MOCK_LAKES)}
