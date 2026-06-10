"""⚪ MOCK — Soil Moisture connector. Returns synthetic 0.25° grids."""
from __future__ import annotations

import random
from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class SoilMoistureConnector(BaseConnector):
    source = DataSource.SOIL_MOISTURE
    expected_cadence = "daily"
    is_mock = True

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        random.seed(789)
        bbox = bbox or BBox(south=27.5, west=85.0, north=28.0, east=86.0)
        cells = []
        lat = bbox.south
        while lat < bbox.north:
            lng = bbox.west
            while lng < bbox.east:
                cells.append({"lat": round(lat, 2), "lng": round(lng, 2), "moisture_pct": round(random.uniform(40, 95), 1)})
                lng += 0.25
            lat += 0.25
        return {"source": "soil_moisture_mock", "resolution_deg": 0.25, "cells": cells, "date": "2026-06-06"}
