"""
Offline tests for v4: multi-model fleet (cooldown, heterogeneous aggregation),
GDACS/ReliefWeb connectors + agent wiring, climatology, runoff routing,
verification scoring, SQLite store, CAP XML safety, API-key middleware.
No network access.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Literal

import pytest
from pydantic import BaseModel

from floodops.queue.event_bus import EventBus

# ── Phase 0: providers + heterogeneous ensemble ─────────────────────────


def test_github_provider_selection():
    from floodops.llm.providers import make_provider

    p = make_provider("github")
    assert p.name == "github"


def test_nvidia_provider_factories():
    # NVIDIA NIM fallback models (GLM 5.1 + MiniMax) on the OpenAI-compatible
    # integrate.api.nvidia.com gateway. Keyless by default → unavailable.
    from floodops.llm.providers import _nvidia, _nvidia_minimax, make_provider

    glm = _nvidia()
    assert glm.name == "nvidia"
    assert "integrate.api.nvidia.com" in glm._base_url
    assert glm._model == "z-ai/glm-5.1"
    assert not glm.available()  # no NVIDIA_API_KEY set in the test env

    mm = _nvidia_minimax()
    assert mm.name == "nvidia-minimax"
    assert mm._model == "minimaxai/minimax-m2.7"

    # Selectable by name; wrapped in the 429-cooldown guard (name preserved).
    assert make_provider("nvidia").name == "nvidia"
    assert make_provider("nvidia-minimax").name == "nvidia-minimax"


def test_nvidia_minimax_key_falls_back_to_shared_key(monkeypatch):
    # The MiniMax model reuses NVIDIA_API_KEY when it has no dedicated key.
    import floodops.llm.providers as prov

    monkeypatch.setattr(prov, "NVIDIA_API_KEY", "nvapi-shared")
    monkeypatch.setattr(prov, "NVIDIA_MINIMAX_API_KEY", "")
    p = prov._nvidia_minimax()
    assert p._api_key == "nvapi-shared"
    assert p.available()


def test_cooldown_marks_provider_unavailable(monkeypatch):
    import floodops.llm.providers as prov

    class Always:
        name = "always"

        def available(self):
            return True

        async def generate(self, prompt, system=None):
            return "ok"

        async def generate_structured(self, prompt, schema, system=None):
            return None

    wrapped = prov.CooldownProvider(Always())
    assert wrapped.available()
    prov._start_cooldown("always")
    assert not wrapped.available()
    prov._PROVIDER_COOLDOWNS.clear()
    assert wrapped.available()


@pytest.mark.asyncio
async def test_client_chain_falls_through_on_cooldown():
    from floodops.llm.client import FloodLLMClient

    class Named:
        def __init__(self, name, available=True):
            self.name = name
            self._avail = available

        def available(self):
            return self._avail

        async def generate(self, prompt, system=None):
            return self.name

        async def generate_structured(self, prompt, schema, system=None):
            return None

    primary = Named("primary", available=False)  # e.g. cooling down
    backup = Named("backup")
    client = FloodLLMClient(provider=primary, extra_providers=[backup])
    assert client.available()  # chain still has a live backend
    assert (await client.generate("x")).startswith("backup")


class _VoteSchema(BaseModel):
    value: float
    confidence: float
    summary: str
    category: Literal["low", "high"] = "low"


def test_aggregate_votes_pinned_semantics():
    from floodops.agents.base import BaseAgent

    runs = [
        (0, _VoteSchema(value=0.2, confidence=0.5, summary="median-run", category="high")),
        (1, _VoteSchema(value=0.9, confidence=0.9, summary="high-run", category="high")),
        (2, _VoteSchema(value=0.1, confidence=0.1, summary="low-run", category="low")),
    ]
    out = BaseAgent._aggregate_votes(runs, _VoteSchema)
    assert out.value == 0.2          # median of floats
    assert out.confidence == 0.5     # median of floats
    assert out.summary == "median-run"  # whole text from median-confidence run
    assert out.category == "high"    # plurality on the Literal field


def test_aggregate_votes_tiebreak_lower_pool_index():
    from floodops.agents.base import BaseAgent

    runs = [
        (1, _VoteSchema(value=0.5, confidence=0.5, summary="pool-1")),
        (0, _VoteSchema(value=0.5, confidence=0.5, summary="pool-0")),
    ]
    out = BaseAgent._aggregate_votes(runs, _VoteSchema)
    assert out.summary == "pool-0"   # equal confidence → lower pool index wins


# ── Phase 1: GDACS + ReliefWeb ───────────────────────────────────────────


def test_gdacs_level_parse_and_intersection():
    from floodops.connectors.gdacs import GDACSConnector
    from floodops.models.geo import BBox

    assert GDACSConnector._level_from_icon(".../gdacs_icons/maps/Red/FL.png") == "red"
    a = BBox(south=27.0, west=85.0, north=28.0, east=86.0)
    assert GDACSConnector._intersects(a, {"south": 27.5, "west": 85.5,
                                          "north": 29.0, "east": 87.0})
    assert not GDACSConnector._intersects(a, {"south": 10.0, "west": 70.0,
                                              "north": 11.0, "east": 71.0})


class StubGDACS:
    def __init__(self, events):
        self._events = events
        self._intersects = __import__(
            "floodops.connectors.gdacs", fromlist=["GDACSConnector"]
        ).GDACSConnector._intersects

    async def get_flood_events(self):
        return self._events


@pytest.mark.asyncio
async def test_sentinel_gdacs_cross_validation_emits_boost():
    from floodops.agents.sentinel import SentinelAgent

    bus = EventBus()
    external, anomalies = [], []
    await bus.subscribe("external_hazards", lambda ch, p: external.append(p))
    await bus.subscribe("anomaly_alerts", lambda ch, p: anomalies.append(p))

    events = [
        {"event_id": "1", "name": "Flood near basin", "alert_level": "red",
         "severity": 0.9,
         "bbox": {"south": 27.5, "west": 85.0, "north": 28.0, "east": 86.0}},
        {"event_id": "2", "name": "Far away green flood", "alert_level": "green",
         "severity": 0.3,
         "bbox": {"south": 10.0, "west": 0.0, "north": 11.0, "east": 1.0}},
    ]
    agent = SentinelAgent(bus, llm=None, gdacs=StubGDACS(events))
    await agent._poll_gdacs()
    assert len(external) == 2                      # all events feed compound
    assert len(anomalies) == 1                     # only the overlapping red one
    assert anomalies[0]["metric"] == "external_flood_confirmation"
    # Dedup: a second poll emits nothing new.
    await agent._poll_gdacs()
    assert len(external) == 2


@pytest.mark.asyncio
async def test_compound_classifies_external_hazard():
    from floodops.agents.compound import CompoundEventAgent

    agent = CompoundEventAgent(EventBus(), llm=None)
    hazard, bbox = agent._classify("external_hazards", {
        "severity": 0.9, "alert_level": "red", "name": "X",
        "bbox": {"south": 27.0, "west": 85.0, "north": 28.0, "east": 86.0},
    })
    assert hazard is not None and hazard.hazard_type == "regional_flood_alert"
    assert hazard.severity == 0.9 and bbox is not None


@pytest.mark.asyncio
async def test_reliefweb_lag_days(monkeypatch):
    from floodops.connectors.reliefweb import ReliefWebConnector

    conn = ReliefWebConnector()

    async def fake_fetch(url, params=None, headers=None):
        created = (datetime.now().astimezone() - timedelta(days=4)).isoformat()
        return {"data": [{"href": "u", "fields": {
            "title": "Nepal flood sitrep", "date": {"created": created}}}]}

    monkeypatch.setattr(conn, "fetch_with_retry", fake_fetch)
    reports = await conn.get_flood_reports()
    assert reports and 3.5 <= reports[0]["report_lag_days"] <= 4.5
    assert "NOT a real-time signal" in reports[0]["context_note"]


# ── Phase 2: climatology + runoff + verification math ───────────────────


def test_climatology_flags_unseasonal_flow():
    from floodops.hydrology.climatology import build_climatology, seasonal_zscores

    times, values = [], []
    for year in range(2000, 2014):  # 14 years
        for md, v in (("01-15", 10.0), ("07-15", 200.0)):
            times.append(f"{year}-{md}")
            values.append(v + (year % 3))  # slight variance
    clim = build_climatology(times, values)
    assert clim is not None
    # 150 m³/s in January is a huge seasonal anomaly; in July it's below normal.
    jan = seasonal_zscores(["2026-01-15"], [150.0], clim)[0][2]
    jul = seasonal_zscores(["2026-07-15"], [150.0], clim)[0][2]
    assert jan > 5.0 and jul < 0.0


def test_climatology_refused_below_min_years():
    from floodops.hydrology.climatology import build_climatology

    times = [f"200{y}-06-01" for y in range(5)]
    assert build_climatology(times, [1.0] * 5) is None


def test_runoff_determinism_and_spread_bounds():
    from floodops.hydrology.runoff import perturb_precip, route_linear_reservoir

    daily = [5.0, 40.0, 10.0, 0.0, 0.0, 2.0, 1.0]
    a = perturb_precip(daily, member_index=7)
    b = perturb_precip(daily, member_index=7)
    assert a == b                                  # member-seeded → deterministic
    for orig, pert in zip(daily, a, strict=True):
        assert orig * 0.8 - 1e-9 <= pert <= orig * 1.2 + 1e-9

    trace = route_linear_reservoir(daily, area_km2=585)
    assert len(trace) >= len(daily) and max(trace) > 0
    # Peak discharge follows the rain peak, not precedes it.
    assert trace.index(max(trace)) >= 1


def test_discharge_to_depth_anchors():
    from floodops.hydrology.runoff import discharge_to_depth

    thresholds = {1: 10.0, 2: 100.0, 5: 150.0, 10: 180.0}
    assert discharge_to_depth(10.0, thresholds) == 0.5    # 1-yr anchor
    assert discharge_to_depth(5.0, thresholds) == 0.25    # below → linear to 0
    assert 0.5 < discharge_to_depth(50.0, thresholds) < 1.0
    assert discharge_to_depth(1e6, thresholds) == 8.0     # capped


def test_verification_score_sample_hit_rules():
    from floodops.obs.verification import score_sample

    days = [f"2026-06-{d:02d}" for d in range(1, 11)]
    thresholds = {2: 100.0}
    flat = [10.0] * 10

    def spike(day_idx):
        v = flat.copy()
        v[day_idx] = 150.0
        return v

    # TP: crossings 2 days apart.
    assert score_sample(days, spike(3), days, spike(5), thresholds)[2] == \
        {"tp": 1, "fp": 0, "fn": 0}
    # FP: predicted only.
    assert score_sample(days, spike(3), days, flat, thresholds)[2] == \
        {"tp": 0, "fp": 1, "fn": 0}
    # FN: observed only.
    assert score_sample(days, flat, days, spike(3), thresholds)[2] == \
        {"tp": 0, "fp": 0, "fn": 1}
    # Both cross but 5 days apart → FP + FN.
    assert score_sample(days, spike(1), days, spike(6), thresholds)[2] == \
        {"tp": 0, "fp": 1, "fn": 1}


# ── Phase 3: store, CAP, API key ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_roundtrip_survives_restart(tmp_path):
    from floodops.obs.store import Store

    path = str(tmp_path / "t.db")
    s = Store(path)
    await s.init()
    await s.save_forecast("f", {"forecast_id": "f1", "watershed_id": "w",
                                "max_return_period_years": 5})
    await s.save_alert("a", {"dispatch_id": "a1", "event_id": "f1",
                             "severity": "WARNING"})
    await s.close()

    s2 = Store(path)
    await s2.init()
    counts = await s2.counts()
    assert counts["forecasts"] == 1 and counts["alerts"] == 1
    assert (await s2.get_alert("a1"))["severity"] == "WARNING"
    await s2.close()


@pytest.mark.asyncio
async def test_store_disabled_is_noop():
    from floodops.obs.store import Store

    s = Store("")
    await s.init()
    assert not s.enabled
    await s.save_forecast("f", {"forecast_id": "x"})  # must not raise
    assert await s.recent_forecasts() == []


def test_cap_xml_well_formed_and_escapes_hostile_input():
    from floodops.models.cap import to_cap_xml

    xml = to_cap_xml({
        "dispatch_id": "d1", "severity": "EMERGENCY",
        "total_reach_estimate": 1000,
        "cell_broadcasts": [{
            "message_text": 'Evacuate <script>x</script> ]]>&"now"',
            "zone_polygon": {"type": "Polygon",
                             "coordinates": [[[85.2, 27.6], [85.4, 27.6],
                                              [85.4, 27.8], [85.2, 27.6]]]},
        }],
    })
    root = ET.fromstring(xml)            # parses back — well-formed
    assert root.tag.endswith("alert")
    assert "<script>" not in xml         # escaped, not raw
    assert "Extreme" in xml and "Immediate" in xml
    # CAP requires an ISO, timezone-qualified <sent> (T separator, +00:00).
    import re
    sent = root.find(f"{{{root.tag.split('}')[0][1:]}}}sent").text
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", sent)


def test_cap_xml_never_raises_on_dirty_input():
    from floodops.models.cap import to_cap_xml

    xml = to_cap_xml({})                 # all defaults
    assert ET.fromstring(xml).tag.endswith("alert")


def test_api_key_middleware(monkeypatch):
    import floodops.config as config

    monkeypatch.setattr(config, "FLOODOPS_API_KEY", "sekrit")
    from fastapi.testclient import TestClient

    from floodops.api.app import create_app

    app = create_app()
    client = TestClient(app)             # no lifespan — middleware fires first
    assert client.get("/api/v1/verification/skill").status_code == 401
    ok = client.get("/api/v1/verification/skill",
                    headers={"X-API-Key": "sekrit"})
    assert ok.status_code == 200 and ok.json()["status"] == "cold_start"
    # Non-API paths stay open.
    assert client.get("/").status_code == 200
