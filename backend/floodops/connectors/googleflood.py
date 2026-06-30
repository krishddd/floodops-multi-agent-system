"""
🔑 KEY-GATED — Google Flood Forecasting API connector (v5).

Source: ``https://floodforecasting.googleapis.com/v1`` — the operational API
serving the LSTM model of Nearing et al., Nature 627, 559–563 (2024), DOI
10.1038/s41586-024-07145-1 (the system behind https://g.co/floodhub). Free of
charge under CC BY 4.0; access requires a Google Cloud API key with the
"Flood Forecasting API" enabled (waitlist:
https://support.google.com/flood-hub/answer/16364306).

Activation: set ``FLOODS_API_KEY`` (the name Google's own colab + docs use) or
``GOOGLE_FLOOD_API_KEY`` in .env — until then ``available`` is False,
``health_check()`` fails and every method returns None (honest, never faked).

This connector mirrors the full surface of Google's
``Google_Flood_Forecasting_API_Usage_Example`` colab:
  * ``get_gauges(bbox)``            — real + virtual (hybas) gauges in an area;
  * ``get_flood_status(bbox)``      — latest per-gauge flood status (severity
    EXTREME | SEVERE | ABOVE_NORMAL | NO_FLOODING | UNKNOWN, forecast trend,
    issue time, and any inundation/notification polygon references);
  * ``query_gauge_forecasts(...)``  — the *quantitative* model forecasts
    (discharge m³/s or level m, multiple lead times) — Hydrology Model API;
  * ``get_gauge_models(...)``       — gauge model metadata incl. the official
    warning/danger/extreme thresholds (return-period 2/5/20yr for discharge);
  * ``get_significant_events(...)`` — clustered major flood events w/ area &
    population impact (the pulsing red circles on Flood Hub);
  * ``get_flash_floods(...)``       — urban flash-flood probabilities (24h);
  * ``get_serialized_polygon(id)``  — inundation / notification / event KML.

All area + search reads paginate via ``nextPageToken`` (the colab pattern).
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

#: Endpoint per-request fan-out limits (from the colab's bucketing comments).
FORECAST_GAUGE_BUCKET = 500
MODEL_GAUGE_BUCKET = 50

#: Hard safety cap on pagination loops (the API is finite; this guards a
#: malformed/looping ``nextPageToken`` from spinning forever).
MAX_PAGES = 200


def _chunks(seq: list[Any], size: int) -> list[list[Any]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


class GoogleFloodConnector(BaseConnector):
    """Google Flood Forecasting API (the Nature-2024 model, operational)."""

    source = DataSource.GOOGLE_FLOOD
    expected_cadence = "several/day"
    is_mock = False

    API_BASE = "https://floodforecasting.googleapis.com/v1"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("cache_ttl_seconds", 1800)
        super().__init__(**kwargs)
        # Accept either name. GOOGLE_FLOOD_API_KEY keeps backward-compat with
        # earlier FloodOps configs; FLOODS_API_KEY is the canonical name used
        # by Google's own colab + Cloud setup, so a user pasting their key in
        # the documented way is picked up automatically.
        if api_key is not None:
            self._api_key = api_key
        else:
            self._api_key = (os.getenv("GOOGLE_FLOOD_API_KEY")
                             or os.getenv("FLOODS_API_KEY", ""))

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

    # ── HTTP primitives ──────────────────────────────────────────────

    async def _post(self, method: str, body: dict) -> dict | None:
        """POST a JSON body to a v1 custom method, keyed. None on failure."""
        if not self.available:
            return None
        cache_key = self._cache_key(method, sorted(body.items(), key=lambda kv: kv[0]))
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

    async def _get(self, path: str,
                   params: dict | list[tuple[str, Any]] | None = None) -> dict | None:
        """GET a v1 resource, keyed. ``params`` may repeat keys (list of
        tuples) for batchGet-style ``names=`` / ``gaugeIds=`` queries. None on
        failure/no key."""
        if not self.available:
            return None
        items = list(params.items()) if isinstance(params, dict) else list(params or [])
        cache_key = self._cache_key(
            "GET", path, sorted((str(k), str(v)) for k, v in items))
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            client = await self._get_client()
            await self._rate_limit_wait()
            resp = await client.get(
                f"{self.API_BASE}/{path}",
                params=items + [("key", self._api_key)],
            )
            resp.raise_for_status()
            data = resp.json()
            self._set_cached(cache_key, data)
            self._last_data_time = datetime.utcnow().isoformat()
            return data
        except Exception:
            return None

    async def _post_all_pages(self, method: str, base_body: dict,
                              list_key: str) -> list[dict] | None:
        """POST + follow ``nextPageToken`` until exhausted (the colab pattern).

        Returns the concatenated ``list_key`` items, or None if the very first
        page fails (no key / network) — partial pages after a mid-pagination
        failure return what was collected so far (honest, never faked).
        """
        items: list[dict] = []
        body = dict(base_body)
        for _ in range(MAX_PAGES):
            data = await self._post(method, body)
            if data is None:
                return items or None
            if "error" in data:
                break
            items.extend(data.get(list_key, []))
            token = data.get("nextPageToken")
            if not token:
                break
            body = {**base_body, "pageToken": token}
        return items

    @staticmethod
    def _search_body(region_code: str, page_size: int = 10000,
                     include_non_quality: bool = True) -> dict:
        """Area-search request body. The API filters by ``regionCode`` (ISO
        3166-1 alpha-2) — verified against the live API; an ``areaFilter``/
        bounding box is rejected (400 INVALID_ARGUMENT). Bbox narrowing is done
        client-side on the returned gauge locations."""
        return {
            "regionCode": region_code,
            "pageSize": page_size,
            "includeNonQualityVerified": include_non_quality,
        }

    @staticmethod
    def _in_bbox(lat: Any, lng: Any, bbox: BBox | None) -> bool:
        """True if (lat,lng) falls in bbox; True when no bbox or no location
        (don't drop a status just because its location is missing)."""
        if bbox is None or lat is None or lng is None:
            return True
        return (bbox.south <= float(lat) <= bbox.north
                and bbox.west <= float(lng) <= bbox.east)

    def _region_for(self, region_code: str | None) -> str:
        from floodops.config import BASIN_REGION_CODE
        return region_code if region_code is not None else BASIN_REGION_CODE

    # ── Gauges & flood status (paginated) ────────────────────────────

    async def get_gauges(self, bbox: BBox | None = None,
                         region_code: str | None = None) -> list[dict] | None:
        """Gauges in the region (all pages), optionally narrowed to ``bbox``.

        ``region_code`` defaults to the configured basin region (``NP``).
        None on failure/no key.
        """
        raw = await self._post_all_pages(
            "gauges:searchGaugesByArea",
            self._search_body(self._region_for(region_code)),
            "gauges",
        )
        if raw is None:
            return None
        if bbox is None:
            return raw
        out = []
        for g in raw:
            loc = g.get("location") or {}
            if self._in_bbox(loc.get("latitude"), loc.get("longitude"), bbox):
                out.append(g)
        return out

    async def get_flood_status(self, bbox: BBox | None = None,
                               region_code: str | None = None) -> list[dict] | None:
        """Latest normalized flood statuses in the region (all pages),
        optionally narrowed to ``bbox``. None on failure.

        Each: ``{gauge_id, severity, severity_weight, forecast_trend,
        quality_verified, issued_time, lat, lng, inundation_map_set,
        notification_polygon_id, source}``.
        """
        raw = await self._post_all_pages(
            "floodStatus:searchLatestFloodStatusByArea",
            self._search_body(self._region_for(region_code)),
            "floodStatuses",
        )
        if raw is None:
            return None
        statuses: list[dict] = []
        for s in raw:
            loc = s.get("gaugeLocation") or {}
            lat, lng = loc.get("latitude"), loc.get("longitude")
            if not self._in_bbox(lat, lng, bbox):
                continue
            severity = str(s.get("severity", "UNKNOWN")).upper()
            statuses.append({
                "gauge_id": s.get("gaugeId", ""),
                "severity": severity,
                "severity_weight": SEVERITY_WEIGHT.get(severity, 0.0),
                "forecast_trend": s.get("forecastTrend", "NO_CHANGE"),
                "quality_verified": bool(s.get("qualityVerified", False)),
                "issued_time": s.get("issuedTime"),
                "lat": lat,
                "lng": lng,
                # Polygon references for inundation footprints (fetch the KML
                # via get_serialized_polygon); present only for some gauges.
                "inundation_map_set": s.get("inundationMapSet"),
                "notification_polygon_id": s.get("serializedNotificationPolygonId"),
                "source": "google-flood-forecasting (Nearing et al. 2024)",
            })
        return statuses

    # ── Hydrology Model API (quantitative forecasts) ─────────────────

    async def query_gauge_forecasts(self, gauge_ids: list[str],
                                    issued_time_start: str,
                                    issued_time_end: str) -> dict | None:
        """Quantitative model forecasts per gauge over an issue-time window.

        ``issued_time_*`` are ``YYYY-MM-DD`` strings (data starts 2023-10-01).
        Returns ``{gauge_id: {forecasts: [...]}}``; each forecast carries
        multiple lead times (``forecastRanges``). None without a key.
        Gauge ids are bucketed (max 500/request, the endpoint limit).
        """
        if not self.available or not gauge_ids:
            return None
        out: dict[str, Any] = {}
        for bucket in _chunks(gauge_ids, FORECAST_GAUGE_BUCKET):
            # gaugeIds repeats once per id (a list nested in a single tuple is
            # NOT expanded by httpx — it would stringify to a bad query).
            params = [("gaugeIds", g) for g in bucket]
            params += [("issuedTimeStart", issued_time_start),
                       ("issuedTimeEnd", issued_time_end)]
            data = await self._get("gauges:queryGaugeForecasts", params)
            if data and "forecasts" in data:
                out.update(data["forecasts"])
        return out

    async def get_gauge_models(self, gauge_ids: list[str]) -> list[dict] | None:
        """Gauge model metadata incl. official warning/danger/extreme
        thresholds (discharge models: return-period 2/5/20yr; level models:
        meters from local authorities). None without a key. Bucketed at 50.
        """
        if not self.available or not gauge_ids:
            return None
        models: list[dict] = []
        for bucket in _chunks(gauge_ids, MODEL_GAUGE_BUCKET):
            data = await self._get(
                "gaugeModels:batchGet",
                [("names", f"gaugeModels/{g}") for g in bucket],
            )
            if data and "gaugeModels" in data:
                models.extend(data["gaugeModels"])
        return models

    # ── Significant events & urban flash floods (paginated search) ───

    async def get_significant_events(self,
                                     region_code: str = "") -> list[dict] | None:
        """Clustered major flood events (area + population impact). An empty
        regionCode searches globally (the colab default); pass an ISO code to
        scope. None without a key."""
        body = {"regionCode": region_code} if region_code else {}
        return await self._post_all_pages(
            "significantEvents:search", body, "significantEvents")

    async def get_flash_floods(self, region_code: str = "") -> list[dict] | None:
        """Urban flash-flood events — 24h probability per urban region. None
        without a key."""
        body = {"regionCode": region_code} if region_code else {}
        return await self._post_all_pages(
            "flashFloods:search", body, "flashFloodEvents")

    # ── Polygons (KML geometry) ──────────────────────────────────────

    async def get_serialized_polygon(self, polygon_id: str) -> str | None:
        """Fetch a serialized polygon's KML (inundation level / notification /
        significant-event footprint). Returns the raw KML string, or None."""
        if not self.available or not polygon_id:
            return None
        data = await self._get(f"serializedPolygons/{polygon_id}")
        if not data:
            return None
        return data.get("kml")
