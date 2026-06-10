"""Orchestrator phase-transition tests.

Proves the one-shot stepping actually ADVANCES phases (the previous full-graph
``ainvoke`` reset to MONITORING and crashed on recursion, so phases never moved).
"""

from __future__ import annotations

import pytest

from floodops.models.enums import FloodPhase
from floodops.models.state import create_initial_state
from floodops.orchestrator.service import OrchestratorService
from floodops.queue.event_bus import EventBus


def _service() -> OrchestratorService:
    svc = OrchestratorService(EventBus(), {"flood_state": create_initial_state()})
    return svc


def _phase(svc: OrchestratorService):
    return svc.global_state["flood_state"]["current_phase"]


@pytest.mark.asyncio
async def test_monitoring_escalates_to_elevated_on_medium_alert():
    svc = _service()
    assert _phase(svc) == FloodPhase.MONITORING
    await svc.handle_anomaly("anomaly_alerts", {"level": "MEDIUM", "metric": "gauge",
                                                "deviation_sigma": 2.7})
    assert _phase(svc) == FloodPhase.ELEVATED


@pytest.mark.asyncio
async def test_elevated_escalates_to_imminent_on_high_probability():
    svc = _service()
    await svc.handle_anomaly("anomaly_alerts", {"level": "HIGH"})
    assert _phase(svc) == FloodPhase.ELEVATED
    await svc.handle_forecast("flood_forecasts", {"max_probability": 0.85})
    assert _phase(svc) == FloodPhase.IMMINENT


@pytest.mark.asyncio
async def test_glof_emergency_bypasses_to_evacuation():
    svc = _service()
    await svc.handle_glof("glof_emergencies", {"lake_id": "L1"})
    assert _phase(svc) == FloodPhase.EVACUATION


@pytest.mark.asyncio
async def test_no_transition_is_a_noop_not_a_reset():
    """A forecast in MONITORING with no alert must NOT reset/advance the phase."""
    svc = _service()
    await svc.handle_forecast("flood_forecasts", {"max_probability": 0.1})
    assert _phase(svc) == FloodPhase.MONITORING
    # Audit log should not accumulate spurious transition entries.
    assert svc.global_state["flood_state"]["phase_transitions"] == []


@pytest.mark.asyncio
async def test_full_escalation_chain_advances_each_step():
    svc = _service()
    # Use HIGH (not CRITICAL) so flooding isn't "confirmed" before evacuation.
    await svc.handle_anomaly("anomaly_alerts", {"level": "HIGH"})
    assert _phase(svc) == FloodPhase.ELEVATED
    await svc.handle_forecast("flood_forecasts", {"max_probability": 0.95})
    assert _phase(svc) == FloodPhase.IMMINENT
    # IMMINENT → EVACUATION: the 0.95 forecast is already present, so completing
    # urban mapping is the gate that unlocks the transition.
    await svc.handle_urban_risk("urban_risk", {"zones": []})
    assert _phase(svc) == FloodPhase.EVACUATION
    # EVACUATION → ACTIVE needs a CRITICAL alert + routes published (set by node).
    await svc.handle_anomaly("anomaly_alerts", {"level": "CRITICAL"})
    assert _phase(svc) == FloodPhase.ACTIVE
    # ACTIVE → POST_FLOOD needs receding + supplies prepositioned.
    await svc.handle_resource("resource_orders", {"supplies_prepositioned": True})
    await svc.handle_receding("flood_receding", {"gauge_id": "G1"})
    assert _phase(svc) == FloodPhase.POST_FLOOD
