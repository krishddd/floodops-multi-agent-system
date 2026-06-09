"""
🟢 LIVE — OpenStreetMap / Overpass API Connector.

Source: Overpass API (overpass-api.de) via osmnx library
Data: Road networks, building footprints, drainage networks

Data cadence: 🔵 On-demand (static infrastructure data, queried as needed)
"""

from __future__ import annotations

from typing import Any, Optional

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class OSMConnector(BaseConnector):
    """OpenStreetMap infrastructure data connector.

    Queries OSM for evacuation-critical infrastructure:
    - Roads: classify by flood passability (surface type, elevation)
    - Buildings: footprints, floor count, use type (residential, hospital, school)
    - Drainage: waterways, canals, storm drains
    """

    source = DataSource.OSM
    expected_cadence = "on-demand"
    is_mock = False

    OVERPASS_BASE = "https://overpass-api.de/api/interpreter"

    def __init__(self, **kwargs: Any) -> None:
        # Building/road data is near-static — cache aggressively (#13).
        kwargs.setdefault("cache_ttl_seconds", 86400)
        super().__init__(**kwargs)

    async def health_check(self) -> bool:
        # Overpass /api/status returns plain text (not JSON), so check the raw
        # HTTP status rather than fetch_with_retry (which parses JSON).
        try:
            client = await self._get_client()
            resp = await client.get("https://overpass-api.de/api/status")
            return resp.status_code < 500
        except Exception:
            return False

    async def fetch_latest(self, bbox: Optional[BBox] = None, **kwargs: Any) -> dict:
        """Fetch road and building data for a bounding box."""
        if bbox is None:
            bbox = BBox(south=27.65, west=85.25, north=27.75, east=85.35)
        return await self.get_roads_and_buildings(bbox)

    async def get_roads_and_buildings(self, bbox: BBox) -> dict:
        """Query Overpass API for roads and buildings.

        NOTE: For production, use osmnx library for cleaner graph extraction.
        The direct Overpass query is shown here for clarity.
        """
        s, w, n, e = bbox.south, bbox.west, bbox.north, bbox.east
        overpass_query = f"""
        [out:json][timeout:60];
        (
          way["highway"~"primary|secondary|tertiary|residential"]({s},{w},{n},{e});
          way["building"]({s},{w},{n},{e});
          way["waterway"]({s},{w},{n},{e});
        );
        out body;
        >;
        out skel qt;
        """

        try:
            client = await self._get_client()
            resp = await client.post(self.OVERPASS_BASE, data={"data": overpass_query})
            resp.raise_for_status()
            data = resp.json()

            roads = [e for e in data.get("elements", []) if e.get("tags", {}).get("highway")]
            buildings = [e for e in data.get("elements", []) if e.get("tags", {}).get("building")]
            waterways = [e for e in data.get("elements", []) if e.get("tags", {}).get("waterway")]

            self._last_data_time = __import__("datetime").datetime.utcnow().isoformat()
            return {
                "roads_count": len(roads),
                "buildings_count": len(buildings),
                "waterways_count": len(waterways),
                "elements": data.get("elements", []),
            }
        except Exception as exc:
            return {"roads_count": 0, "buildings_count": 0, "waterways_count": 0, "error": str(exc)}

    async def get_shelters(self, bbox: BBox) -> list[dict]:
        """Query OSM for emergency shelters and community buildings."""
        s, w, n, e = bbox.south, bbox.west, bbox.north, bbox.east
        query = f"""
        [out:json][timeout:30];
        (
          node["emergency"="assembly_point"]({s},{w},{n},{e});
          node["amenity"~"shelter|community_centre|school"]({s},{w},{n},{e});
        );
        out body;
        """
        try:
            client = await self._get_client()
            resp = await client.post(self.OVERPASS_BASE, data={"data": query})
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            return [{
                "id": el.get("id"),
                "lat": el.get("lat"),
                "lng": el.get("lon"),
                "name": el.get("tags", {}).get("name", "Unnamed"),
                "type": el.get("tags", {}).get("amenity", "shelter"),
            } for el in elements]
        except Exception:
            return []
