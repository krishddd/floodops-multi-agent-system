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
    from floodops.connectors.googleflood import GoogleFloodConnector

    conn = GoogleFloodConnector(api_key="")
    assert not conn.available


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
        assert body["areaFilter"]["boundingBox"]["southWest"]["latitude"] == 27.0
        return {"floodStatuses": [{
            "gaugeId": "hybas_4121489010", "severity": "SEVERE",
            "forecastTrend": "RISE", "qualityVerified": True,
            "issuedTime": "2026-06-10T00:00:00Z",
            "gaugeLocation": {"latitude": 27.7, "longitude": 85.3},
        }]}

    monkeypatch.setattr(conn, "_post", fake_post)
    statuses = await conn.get_flood_status(
        BBox(south=27.0, west=85.0, north=28.0, east=86.0)
    )
    assert statuses and statuses[0]["severity"] == "SEVERE"
    assert statuses[0]["severity_weight"] == 0.8
    assert statuses[0]["forecast_trend"] == "RISE"
    assert statuses[0]["quality_verified"] is True


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
