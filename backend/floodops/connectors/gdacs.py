"""
🟢 LIVE (keyless) — GDACS global disaster alert connector.

Source: Global Disaster Alert and Coordination System (EC JRC + UN OCHA),
``https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP`` — GeoJSON of
active disaster events with an alert level (Green/Orange/Red), bbox and
episode dates. Coordinates are WGS84.

Used as an INDEPENDENT confirmation signal: SentinelAgent cross-validates its
anomaly detection against active Orange/Red flood events, and the
CompoundEventAgent receives them as a contributing regional hazard. Never a
forecast-model input.

Terms-of-service note: GDACS distinguishes research/educational use from
operational/commercial use. This connector is demo/evaluation-grade; a real
agency deployment requires a GDACS data-sharing agreement.

No API key required. Cache TTL 900s; every method degrades to ``None``/[] on
failure so consumers fall back to their deterministic behaviour.
"""

from __future__ import annotations

from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox

#: Numeric severity per GDACS alert level (deterministic, used by consumers).
ALERT_LEVEL_SEVERITY = {"green": 0.3, "orange": 0.6, "red": 0.9}


class GDACSConnector(BaseConnector):
    """Keyless global disaster-event feed (flood events by default)."""

    source = DataSource.GDACS
    expected_cadence = "continuous"
    is_mock = False

    EVENTS_BASE = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("cache_ttl_seconds", 900)
        super().__init__(**kwargs)

    async def health_check(self) -> bool:
        try:
            await self.fetch_with_retry(self.EVENTS_BASE, params={"eventtypes": "FL"})
            return True
        except Exception:
            return False

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        """Active flood events, optionally filtered to those intersecting ``bbox``."""
        events = await self.get_flood_events() or []
        if bbox is not None:
            events = [e for e in events
                      if e.get("bbox") and self._intersects(bbox, e["bbox"])]
        return {"events": events}

    async def get_flood_events(self, event_types: str = "FL") -> list[dict] | None:
        """Normalized active events. Returns None on failure (never faked).

        Each event: ``{event_id, name, alert_level, severity, bbox{...},
        from_date, to_date, report_url}`` — ``severity`` maps the GDACS alert
        level through ``ALERT_LEVEL_SEVERITY``.
        """
        try:
            data = await self.fetch_with_retry(
                self.EVENTS_BASE, params={"eventtypes": event_types}
            )
            events: list[dict] = []
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                level = str(
                    props.get("alertlevel")
                    or self._level_from_icon(props.get("icon", ""))
                ).lower()
                fb = feat.get("bbox")  # GeoJSON order: [w, s, e, n]
                bbox = None
                if isinstance(fb, list) and len(fb) >= 4:
                    bbox = BBox(west=fb[0], south=fb[1], east=fb[2], north=fb[3])
                events.append({
                    "event_id": str(props.get("eventid", "")),
                    "name": props.get("name") or props.get("description", ""),
                    "alert_level": level,
                    "severity": ALERT_LEVEL_SEVERITY.get(level, 0.3),
                    "bbox": bbox.model_dump() if bbox else None,
                    "from_date": props.get("fromdate"),
                    "to_date": props.get("todate"),
                    "report_url": (props.get("url") or {}).get("report"),
                })
            return events
        except Exception:
            return None

    @staticmethod
    def _level_from_icon(icon_url: str) -> str:
        """Fallback alert-level parse from the icon path (…/Green/FL.png)."""
        for level in ("red", "orange", "green"):
            if f"/{level}/" in icon_url.lower():
                return level
        return "green"

    @staticmethod
    def _intersects(a: BBox, b: dict | BBox) -> bool:
        """Rectangle intersection in WGS84 — an explicit approximation.

        Real basins are not rectangles; this biases toward false positives,
        which is the conservative direction for alert cross-validation.
        """
        bb = b if isinstance(b, BBox) else BBox(**b)
        return not (bb.west > a.east or bb.east < a.west
                    or bb.south > a.north or bb.north < a.south)
