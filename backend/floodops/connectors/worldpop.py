"""⚪ MOCK — WorldPop population density. Returns synthetic 100m grids."""
from __future__ import annotations

import random
from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class WorldPopConnector(BaseConnector):
    source = DataSource.WORLDPOP
    expected_cadence = "annual"
    is_mock = True

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        random.seed(321)
        bbox = bbox or BBox(south=27.6, west=85.2, north=27.8, east=85.4)
        cells = []
        lat = bbox.south
        while lat < bbox.north:
            lng = bbox.west
            while lng < bbox.east:
                pop = max(0, int(random.gauss(150, 80)))
                cells.append({"lat": round(lat, 4), "lng": round(lng, 4), "population": pop})
                lng += 0.001  # ~100m
            lat += 0.001
        return {"source": "worldpop_mock", "resolution_m": 100, "year": 2025, "cells": cells[:500], "total_cells": len(cells)}
