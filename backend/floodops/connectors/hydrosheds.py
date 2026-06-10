"""⚪ MOCK — HydroSHEDS watershed/river network. Returns cached watershed boundaries."""
from __future__ import annotations

from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource


class HydroSHEDSConnector(BaseConnector):
    source = DataSource.HYDROSHEDS
    expected_cadence = "static"
    is_mock = True

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, **kwargs: Any) -> dict:
        return {
            "source": "hydrosheds_mock",
            "watersheds": [
                {"basin_id": "HB_4527", "name": "Bagmati Basin", "area_km2": 3640, "outlet": {"lat": 27.61, "lng": 85.32}, "level": 7},
                {"basin_id": "HB_4528", "name": "Koshi Basin", "area_km2": 54100, "outlet": {"lat": 26.52, "lng": 86.92}, "level": 5},
            ],
            "river_network_km": 1245.6,
        }
