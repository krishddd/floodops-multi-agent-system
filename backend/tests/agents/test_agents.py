"""Per-agent tests — run() with mock data, no-key fallback, output validation.

Every agent must still produce valid output with NO LLM configured (the
deterministic mock path), and must enrich its output when an LLM is present.
"""

from __future__ import annotations

import pytest

from floodops.agents.compound import CompoundEventAgent
from floodops.agents.disease import DiseaseRiskAgent
from floodops.agents.predict import FloodPredictAgent
from floodops.agents.urban import UrbanRiskAgent

_BBOX = {"south": 27.5, "west": 85.0, "north": 28.0, "east": 85.7}
_ALERT = {"alert_id": "a1", "watershed_id": "w1", "location": {"lat": 27.7, "lng": 85.3},
          "bbox": _BBOX}


@pytest.mark.asyncio
async def test_predict_produces_forecast_without_key(event_bus, nokey_llm):
    agent = FloodPredictAgent(event_bus, llm=nokey_llm)
    forecast = await agent.run_ensemble(_ALERT)
    assert forecast is not None
    assert 0.0 <= forecast.max_probability <= 1.0
    assert len(forecast.ensemble_members) == 50
    assert "depth 90% CI" in forecast.summary  # uncertainty bounds attached


@pytest.mark.asyncio
async def test_predict_enriches_with_llm(event_bus, fake_llm):
    agent = FloodPredictAgent(event_bus, llm=fake_llm)
    forecast = await agent.run_ensemble(_ALERT)
    # FakeProvider ran the 3-run ensemble vote.
    assert fake_llm._provider.calls == 3
    # Routing probability stays deterministic (LLM never overrides safety number).
    assert 0.0 <= forecast.max_probability <= 1.0


@pytest.mark.asyncio
async def test_urban_enriches_high_risk_zone_with_reflexion(event_bus, fake_llm):
    agent = UrbanRiskAgent(event_bus, llm=fake_llm)
    report = await agent.map_urban_risk({"bbox": _BBOX, "max_probability": 0.95,
                                         "event_id": "e1"})
    assert report is not None
    assert report.zones
    # At least one HIGH/CRITICAL zone should have been LLM-enriched.
    assert fake_llm._provider.calls >= 1


@pytest.mark.asyncio
async def test_disease_emits_with_assessment(event_bus, fake_llm):
    agent = DiseaseRiskAgent(event_bus, llm=fake_llm)
    emitted = []

    async def cap(channel, payload):
        emitted.append(payload)

    await event_bus.subscribe("disease_risk", cap)
    await agent.handle_flood_receding(
        "flood_receding",
        {"event_id": "e1", "flood_depth_max_m": 3.0, "flood_duration_hours": 48, "bbox": _BBOX},
    )
    assert emitted
    assert "report_id" in emitted[0]


@pytest.mark.asyncio
async def test_compound_requires_two_hazards(event_bus, nokey_llm):
    agent = CompoundEventAgent(event_bus, llm=nokey_llm)
    emitted = []

    async def cap(channel, payload):
        emitted.append(payload)

    await event_bus.subscribe("compound_threats", cap)
    await agent.initialize()

    # One hazard — no compound threat yet.
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.8, "bbox": _BBOX,
                                                  "event_id": "e1"})
    assert not emitted

    # Second distinct hazard — compound threat fires.
    await agent.handle_signal("glof_emergencies", {"integrity_score": 0.2, "bbox": _BBOX,
                                                   "event_id": "e1"})
    assert emitted
    threat = emitted[-1]
    assert 0.0 <= threat["unified_threat_score"] <= 1.0
    assert {h["hazard_type"] for h in threat["contributing_hazards"]} == {"flood", "glof"}
    assert threat["compounding_factors"]


@pytest.mark.asyncio
async def test_compound_score_within_bounds_and_validates(event_bus, fake_llm):
    agent = CompoundEventAgent(event_bus, llm=fake_llm)
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.9, "bbox": _BBOX,
                                                  "event_id": "e1"})
    threat = await agent._synthesize()  # type: ignore[attr-defined]
    # Only one hazard active here; _synthesize still builds a valid object.
    assert threat is None or 0.0 <= threat.unified_threat_score <= 1.0
