"""
Offline tests for v5: Google Flood Forecasting connector (key-gated),
sentinel cross-validation wiring, and runoff calibration. No network access.
"""

from __future__ import annotations

import pytest

from floodops.queue.event_bus import EventBus

# ── Google Flood connector ───────────────────────────────────────────────


def test_googleflood_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_FLOOD_API_KEY", raising=False)
    monkeypatch.delenv("FLOODS_API_KEY", raising=False)
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector(api_key="")
    assert not conn.available


def test_googleflood_accepts_floods_api_key_alias(monkeypatch):
    # The name Google's own colab/docs use — a key pasted the documented way
    # must activate the connector.
    monkeypatch.delenv("GOOGLE_FLOOD_API_KEY", raising=False)
    monkeypatch.setenv("FLOODS_API_KEY", "AIza-from-colab")
    from floodops.connectors.googleflood import GoogleFloodConnector

    assert GoogleFloodConnector().available


def test_googleflood_key_precedence(monkeypatch):
    # GOOGLE_FLOOD_API_KEY wins when both are set (backward-compat).
    monkeypatch.setenv("GOOGLE_FLOOD_API_KEY", "legacy")
    monkeypatch.setenv("FLOODS_API_KEY", "canonical")
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector()
    assert conn.available and conn._api_key == "legacy"


@pytest.mark.asyncio
async def test_googleflood_health_and_fetch_fail_without_key():
    from floodops.connectors.googleflood import GoogleFloodConnector
    from floodops.models.geo import BBox

    conn = GoogleFloodConnector(api_key="")
    assert not await conn.health_check()
    bbox = BBox(south=27.0, west=85.0, north=28.0, east=86.0)
    assert await conn.get_flood_status(bbox) is None  # honest None, no network


@pytest.mark.asyncio
async def test_googleflood_normalizes_statuses(monkeypatch):
    from floodops.connectors.googleflood import GoogleFloodConnector
    from floodops.models.geo import BBox

    conn = GoogleFloodConnector(api_key="k")

    async def fake_post(method, body):
        assert method == "floodStatus:searchLatestFloodStatusByArea"
        # The live API filters by regionCode, NOT a bbox areaFilter (verified
        # against the API: areaFilter → 400 INVALID_ARGUMENT).
        assert body["regionCode"] == "NP"
        assert "areaFilter" not in body
        return {"floodStatuses": [{
            "gaugeId": "hybas_4121489010", "severity": "SEVERE",
            "forecastTrend": "RISE", "qualityVerified": True,
            "issuedTime": "2026-06-10T00:00:00Z",
            "gaugeLocation": {"latitude": 27.7, "longitude": 85.3},
        }]}

    monkeypatch.setattr(conn, "_post", fake_post)
    statuses = await conn.get_flood_status(
        BBox(south=27.0, west=85.0, north=28.0, east=86.0)  # contains 27.7,85.3
    )
    assert statuses and statuses[0]["severity"] == "SEVERE"
    assert statuses[0]["severity_weight"] == 0.8
    assert statuses[0]["forecast_trend"] == "RISE"
    assert statuses[0]["quality_verified"] is True
    assert (statuses[0]["lat"], statuses[0]["lng"]) == (27.7, 85.3)


@pytest.mark.asyncio
async def test_googleflood_bbox_filters_client_side(monkeypatch):
    # Region search returns the whole country; the connector narrows to bbox.
    from floodops.connectors.googleflood import GoogleFloodConnector
    from floodops.models.geo import BBox

    conn = GoogleFloodConnector(api_key="k")

    async def fake_post(method, body):
        return {"floodStatuses": [
            {"gaugeId": "in", "severity": "SEVERE",
             "gaugeLocation": {"latitude": 27.7, "longitude": 85.3}},
            {"gaugeId": "out", "severity": "EXTREME",
             "gaugeLocation": {"latitude": 10.0, "longitude": 80.0}},
        ]}

    monkeypatch.setattr(conn, "_post", fake_post)
    statuses = await conn.get_flood_status(
        BBox(south=27.0, west=85.0, north=28.0, east=86.0))
    assert [s["gauge_id"] for s in statuses] == ["in"]


@pytest.mark.asyncio
async def test_googleflood_paginates_statuses(monkeypatch):
    # get_flood_status must follow nextPageToken (the colab pattern), not stop
    # at the first page.
    from floodops.connectors.googleflood import GoogleFloodConnector
    from floodops.models.geo import BBox

    conn = GoogleFloodConnector(api_key="k")
    pages = {
        None: {"floodStatuses": [{"gaugeId": "a", "severity": "SEVERE"}],
               "nextPageToken": "p2"},
        "p2": {"floodStatuses": [{"gaugeId": "b", "severity": "EXTREME"}]},
    }
    calls = {"n": 0}

    async def fake_post(method, body):
        calls["n"] += 1
        return pages[body.get("pageToken")]

    monkeypatch.setattr(conn, "_post", fake_post)
    statuses = await conn.get_flood_status(BBox(south=27, west=85, north=28, east=86))
    assert calls["n"] == 2
    assert [s["gauge_id"] for s in statuses] == ["a", "b"]
    assert statuses[1]["severity_weight"] == 0.95


@pytest.mark.asyncio
async def test_googleflood_query_forecasts_buckets_and_merges(monkeypatch):
    from floodops.connectors import googleflood as gf

    conn = gf.GoogleFloodConnector(api_key="k")
    monkeypatch.setattr(gf, "FORECAST_GAUGE_BUCKET", 2)  # force two buckets
    seen_buckets = []

    async def fake_get(path, params=None):
        assert path == "gauges:queryGaugeForecasts"
        # gaugeIds is repeated once per id (httpx-safe), not a nested list.
        ids = [v for k, v in params if k == "gaugeIds"]
        seen_buckets.append(tuple(ids))
        return {"forecasts": {gid: {"forecasts": [{"lead": 1}]} for gid in ids}}

    monkeypatch.setattr(conn, "_get", fake_get)
    out = await conn.query_gauge_forecasts(
        ["g1", "g2", "g3"], "2026-06-22", "2026-06-30")
    assert seen_buckets == [("g1", "g2"), ("g3",)]
    assert set(out) == {"g1", "g2", "g3"}


@pytest.mark.asyncio
async def test_googleflood_gauge_models_batchget(monkeypatch):
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector(api_key="k")

    async def fake_get(path, params=None):
        assert path == "gaugeModels:batchGet"
        names = [v for k, v in params if k == "names"]
        return {"gaugeModels": [{"name": n} for n in names]}

    monkeypatch.setattr(conn, "_get", fake_get)
    models = await conn.get_gauge_models(["g1", "g2"])
    assert {m["name"] for m in models} == {"gaugeModels/g1", "gaugeModels/g2"}


@pytest.mark.asyncio
async def test_googleflood_significant_events_and_flash_floods(monkeypatch):
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector(api_key="k")

    async def fake_post(method, body):
        if method == "significantEvents:search":
            return {"significantEvents": [{"eventPolygonId": "poly1"}]}
        if method == "flashFloods:search":
            return {"flashFloodEvents": [{"region": "urban1"}]}
        raise AssertionError(method)

    monkeypatch.setattr(conn, "_post", fake_post)
    events = await conn.get_significant_events()
    floods = await conn.get_flash_floods()
    assert events[0]["eventPolygonId"] == "poly1"
    assert floods[0]["region"] == "urban1"


@pytest.mark.asyncio
async def test_googleflood_serialized_polygon(monkeypatch):
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector(api_key="k")

    async def fake_get(path, params=None):
        assert path == "serializedPolygons/poly1"
        return {"kml": "<kml>...</kml>"}

    monkeypatch.setattr(conn, "_get", fake_get)
    assert await conn.get_serialized_polygon("poly1") == "<kml>...</kml>"
    # No key / empty id → honest None, no network.
    assert await GoogleFloodConnector(api_key="").get_serialized_polygon("x") is None
    assert await conn.get_serialized_polygon("") is None


class StubGoogleFlood:
    available = True

    def __init__(self, statuses):
        self._statuses = statuses

    async def get_flood_status(self, bbox):
        return self._statuses


@pytest.mark.asyncio
async def test_sentinel_googleflood_boosts_on_severe():
    from floodops.agents.sentinel import SentinelAgent

    bus = EventBus()
    external, anomalies = [], []
    await bus.subscribe("external_hazards", lambda ch, p: external.append(p))
    await bus.subscribe("anomaly_alerts", lambda ch, p: anomalies.append(p))

    statuses = [
        {"gauge_id": "g1", "severity": "EXTREME", "severity_weight": 0.95,
         "forecast_trend": "RISE", "quality_verified": True,
         "issued_time": "t1", "lat": 27.7, "lng": 85.3},
        {"gauge_id": "g2", "severity": "NO_FLOODING", "severity_weight": 0.1,
         "forecast_trend": "NO_CHANGE", "quality_verified": True,
         "issued_time": "t1", "lat": 27.6, "lng": 85.2},
    ]
    agent = SentinelAgent(bus, llm=None, googleflood=StubGoogleFlood(statuses))
    await agent._poll_googleflood()
    assert len(external) == 2
    assert len(anomalies) == 1
    assert anomalies[0]["metric"] == "ai_model_flood_forecast"
    assert anomalies[0]["level"] == "CRITICAL"   # EXTREME → CRITICAL
    assert anomalies[0]["confidence"] == 0.95    # quality-verified gauge
    # Dedup on (gauge, issued_time): second poll emits nothing.
    await agent._poll_googleflood()
    assert len(external) == 2 and len(anomalies) == 1


# ── Runoff calibration ───────────────────────────────────────────────────


def _synthetic_record(years=15, scale_truth=2.0, area_km2=585.0):
    """Daily precip + discharge where discharge = routed precip × truth."""
    from floodops.hydrology.runoff import route_linear_reservoir

    p_times, p_vals, q_times, q_vals = [], [], [], []
    for year in range(2000, 2000 + years):
        precip = [(d * 7919 % 23) if d % 11 else 40.0 + (year % 5)
                  for d in range(365)]
        routed = route_linear_reservoir(precip, area_km2)
        for d in range(365):
            day = f"{year}-{(d // 31) % 12 + 1:02d}-{d % 28 + 1:02d}"
            p_times.append(day)
            p_vals.append(precip[d])
            q_times.append(day)
            q_vals.append(routed[d] * scale_truth)
    return p_times, p_vals, q_times, q_vals


def test_calibration_recovers_known_scale():
    from floodops.hydrology.calibration import calibrate_runoff_scale

    p_t, p_v, q_t, q_v = _synthetic_record(scale_truth=2.0)
    out = calibrate_runoff_scale(p_t, p_v, q_t, q_v, area_km2=585.0)
    assert out is not None
    assert out["paired_years"] == 15
    # Median ratio must recover the synthetic truth closely.
    assert 1.8 <= out["scale"] <= 2.2
    assert out["ratio_p25"] <= out["scale"] <= out["ratio_p75"] + 1e-9


def test_calibration_refused_on_short_record():
    from floodops.hydrology.calibration import calibrate_runoff_scale

    p_t, p_v, q_t, q_v = _synthetic_record(years=5)
    assert calibrate_runoff_scale(p_t, p_v, q_t, q_v, area_km2=585.0) is None


def test_calibration_refused_on_degenerate_scale():
    from floodops.hydrology.calibration import calibrate_runoff_scale

    # Discharge a million times the routed value → outside SCALE_BOUNDS.
    p_t, p_v, q_t, q_v = _synthetic_record(scale_truth=1e6)
    assert calibrate_runoff_scale(p_t, p_v, q_t, q_v, area_km2=585.0) is None
