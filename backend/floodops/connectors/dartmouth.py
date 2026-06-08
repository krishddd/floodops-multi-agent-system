"""⚪ MOCK — Dartmouth Flood Observatory. Returns historical flood event stubs."""
from __future__ import annotations
from typing import Any
from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource

class DartmouthConnector(BaseConnector):
    source = DataSource.DARTMOUTH
    expected_cadence = "event-based"
    is_mock = True

    async def health_check(self) -> bool:
        return True

    async def fetch_latest(self, **kwargs: Any) -> dict:
        return {
            "source": "dartmouth_mock",
            "events": [
                {"event_id": "DFO_4935", "country": "Nepal", "start": "2024-07-15", "end": "2024-08-02", "severity": 1.5, "dead": 120, "displaced": 45000, "area_km2": 2800},
                {"event_id": "DFO_4812", "country": "Nepal", "start": "2023-08-20", "end": "2023-09-05", "severity": 2.0, "dead": 85, "displaced": 32000, "area_km2": 1950},
                {"event_id": "DFO_4701", "country": "Nepal", "start": "2022-07-28", "end": "2022-08-15", "severity": 1.8, "dead": 200, "displaced": 78000, "area_km2": 4200},
            ],
        }
