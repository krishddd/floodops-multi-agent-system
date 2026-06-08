"""⚪ MOCK — Sentinel Hub SAR connector. Returns realistic SAR-derived flood extent stubs."""
from __future__ import annotations
from typing import Any, Optional
from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonFeature, GeoJsonGeometry

class SentinelHubConnector(BaseConnector):
    source = DataSource.SENTINEL_SAR
    expected_cadence = "6-12 days"
    is_mock = True

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, bbox: Optional[BBox] = None, **kwargs: Any) -> dict:
        bbox = bbox or BBox(south=27.6, west=85.2, north=27.8, east=85.4)
        return {
            "source": "sentinel_hub_mock",
            "flood_extent": GeoJsonFeatureCollection(features=[
                GeoJsonFeature(
                    geometry=GeoJsonGeometry(type="Polygon", coordinates=[[[85.25, 27.65], [85.35, 27.65], [85.35, 27.75], [85.25, 27.75], [85.25, 27.65]]]),
                    properties={"flood_detected": True, "water_fraction": 0.42, "confidence": 0.78},
                ),
            ]).model_dump(),
            "acquisition_date": "2026-06-05T06:30:00Z",
            "orbit_direction": "ascending",
            "data_cadence_badge": self.get_cadence_badge().model_dump(),
        }
