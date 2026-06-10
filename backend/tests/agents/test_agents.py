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
from floodops.models.geo import BBox

_BBOX = {"south": 27.5, "west": 85.0, "north": 28.0, "east": 85.7}
_ALERT = {"alert_id": "a1", "watershed_id": "w1", "location": {"lat": 27.7, "lng": 85.3},
          "bbox": _BBOX}


def _bbox_obj() -> BBox:
    return BBox(**_BBOX)


@pytest.mark.asyncio
async def test_predict_produces_forecast_without_key(event_bus, nokey_llm):
    agent = FloodPredictAgent(event_bus, llm=nokey_llm)
    forecast = await agent.run_ensemble(_ALERT)
    assert forecast is not None
    assert 0.0 <= forecast.max_probability <= 1.0
    assert len(forecast.ensemble_members) == 50
    assert "depth 90% CI" in forecast.summary  # uncertainty bounds attached


@pytest.mark.asyncio
async def test_predict_return_period_classification(event_bus, nokey_llm):
    """Paper-aligned (Nature 627, 2024): forecasts carry return-period exceedance."""
    agent = FloodPredictAgent(event_bus, llm=nokey_llm)
    forecast = await agent.run_ensemble(_ALERT)
    rps = forecast.return_period_events
    assert [e.return_period_years for e in rps] == [1, 2, 5, 10]
    # Exceedance is monotonically non-increasing as the event gets rarer.
    probs = [e.exceedance_probability for e in rps]
    assert probs == sorted(probs, reverse=True)
    assert all(0.0 <= p <= 1.0 for p in probs)
    # Headline return period is reflected in the summary.
    if forecast.max_return_period_years is not None:
        assert f"{forecast.max_return_period_years}-yr" in forecast.summary


@pytest.mark.asyncio
async def test_predict_lead_time_skill_horizon(event_bus, nokey_llm):
    """Paper-aligned: skill decays across the 7-day horizon; horizon is reported."""
    agent = FloodPredictAgent(event_bus, llm=nokey_llm)
    forecast = await agent.run_ensemble(_ALERT)
    skill = forecast.lead_time_skill
    assert [s.lead_time_days for s in skill] == list(range(8))  # days 0..7
    # Retention is highest at nowcast and never increases with lead time.
    f1s = [s.estimated_f1 for s in skill]
    assert f1s == sorted(f1s, reverse=True)
    assert skill[0].skill_retention == 1.0
    # Effective warning horizon is a real lead day within the 7-day window.
    assert forecast.skillful_lead_days is None or 0 <= forecast.skillful_lead_days <= 7


class _FakeMeteoConnector:
    """Offline connector returning paper-faithful meteorology (no network)."""

    def __init__(self, payload):
        self._payload = payload

    async def fetch_latest(self, bbox=None, **kwargs):
        return self._payload


@pytest.mark.asyncio
async def test_predict_uses_meteorology_forcing_not_discharge(event_bus, nokey_llm):
    """Paper-aligned: precip + snowmelt drive intensity; GloFAS discharge is not an input."""
    payload = {
        "meteorology": {
            "precip_total_72h_mm": 150.0,
            "positive_degree_hours_72h": 400.0,
            "snowfall_total_72h_cm": 5.0,
        },
        # A wildly high discharge must NOT influence the forecast intensity.
        "discharge": {"max": [99999.0]},
    }
    agent = FloodPredictAgent(event_bus, llm=nokey_llm,
                              connector=_FakeMeteoConnector(payload))
    mult, source = await agent._forcing_intensity(_bbox_obj())
    # 0.7 + 150/150 + min(0.4, 400/400) => capped at 2.0; snowmelt term present.
    assert mult == 2.0
    assert "precip 150mm" in source and "melt" in source


@pytest.mark.asyncio
async def test_predict_forcing_falls_back_to_rainfall(event_bus, nokey_llm):
    """No meteorology payload → precipitation-only path still works (back-compat)."""
    agent = FloodPredictAgent(event_bus, llm=nokey_llm,
                              connector=_FakeMeteoConnector({"rainfall": {"total_72h_mm": 75.0}}))
    mult, source = await agent._forcing_intensity(_bbox_obj())
    assert mult == round(0.7 + 75.0 / 150.0, 2)
    assert "75mm" in source


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
async def test_compound_dedup_one_emission_per_hazard_set(event_bus, nokey_llm):
    """B4: repeated signals of an already-present hazard type at a similar score
    must NOT re-emit — one emission per new hazard-type combination."""
    agent = CompoundEventAgent(event_bus, llm=nokey_llm)
    emitted = []

    async def cap(channel, payload):
        emitted.append(payload)

    await event_bus.subscribe("compound_threats", cap)

    # flood + glof → first compound emission.
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.9, "bbox": _BBOX,
                                                  "event_id": "e1"})
    await agent.handle_signal("glof_emergencies", {"integrity_score": 0.2, "bbox": _BBOX,
                                                   "event_id": "e1"})
    assert len(emitted) == 1

    # Another flood signal at a similar score, same {flood, glof} set → NO re-emit.
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.91, "bbox": _BBOX,
                                                  "event_id": "e2"})
    assert len(emitted) == 1, "dedup failed — re-emitted on repeat hazard type"

    # A NEW hazard type (disease) changes the set → emit again.
    await agent.handle_signal("disease_risk",
                              {"hotspots": [{"risk_score": 0.8}], "bbox": _BBOX, "event_id": "e3"})
    assert len(emitted) == 2


@pytest.mark.asyncio
async def test_compound_no_overlap_no_compound(event_bus, nokey_llm):
    """B4 spatial: hazards in non-overlapping regions must not compound."""
    agent = CompoundEventAgent(event_bus, llm=nokey_llm)
    emitted = []

    async def cap(channel, payload):
        emitted.append(payload)

    await event_bus.subscribe("compound_threats", cap)
    far = {"south": 10.0, "west": 10.0, "north": 10.5, "east": 10.5}
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.9, "bbox": _BBOX})
    await agent.handle_signal("glof_emergencies", {"integrity_score": 0.2, "bbox": far})
    assert emitted == []


@pytest.mark.asyncio
async def test_compound_score_within_bounds_and_validates(event_bus, fake_llm):
    agent = CompoundEventAgent(event_bus, llm=fake_llm)
    await agent.handle_signal("flood_forecasts", {"max_probability": 0.9, "bbox": _BBOX,
                                                  "event_id": "e1"})
    threat = await agent._synthesize()  # type: ignore[attr-defined]
    # Only one hazard active here; _synthesize still builds a valid object.
    assert threat is None or 0.0 <= threat.unified_threat_score <= 1.0
