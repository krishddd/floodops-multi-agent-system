"""Flood state, simulation, and chat endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks

from floodops.api.app import get_event_bus, get_reasoner, get_state
from floodops.models.enums import AlertLevel, FloodPhase
from floodops.models.geo import BBox, Coordinate
from floodops.models.sentinel import AnomalyAlert

router = APIRouter()


@router.get("/state")
async def get_flood_state() -> dict:
    """Get the current flood system state."""
    state = get_state()
    return {
        "current_phase": state.get("current_phase", FloodPhase.MONITORING),
        "event_id": state.get("event_id", ""),
        "phase_entered_at": state.get("phase_entered_at", ""),
        "gate_conditions": {
            "urban_mapping_complete": state.get("urban_mapping_complete", False),
            "evacuation_routes_published": state.get("evacuation_routes_published", False),
            "supplies_prepositioned": state.get("supplies_prepositioned", False),
            "outbreak_risk_cleared": state.get("outbreak_risk_cleared", False),
        },
        "counts": {
            "active_alerts": len(state.get("active_alerts", [])),
            "flood_forecasts": len(state.get("flood_forecasts", [])),
            "urban_risk_reports": len(state.get("urban_risk_reports", [])),
            "alert_dispatches": len(state.get("alert_dispatches", [])),
        },
    }


@router.get("/phase")
async def get_current_phase() -> dict:
    state = get_state()
    return {"phase": state.get("current_phase", FloodPhase.MONITORING), "entered_at": state.get("phase_entered_at", "")}


@router.get("/audit")
async def get_audit_log() -> list:
    state = get_state()
    entries = state.get("audit_log", [])
    return [e.model_dump() if hasattr(e, "model_dump") else e for e in entries[-50:]]


@router.get("/agents")
async def get_agent_status() -> list[dict]:
    from floodops.api.app import _app_state
    agents = _app_state.get("agents", [])
    return [{"agent_id": a.agent_id, "trigger_types": [t.value for t in a.trigger_types]} for a in agents]


@router.post("/simulate")
async def simulate_flood_event(background_tasks: BackgroundTasks) -> dict:
    """Inject a mock flood event to trigger the full pipeline asynchronously."""
    bus = get_event_bus()
    alert = AnomalyAlert(
        alert_id=str(uuid.uuid4()),
        level=AlertLevel.HIGH,
        metric="water_level",
        value=4.2,
        deviation_sigma=3.8,
        location=Coordinate(lat=27.7, lng=85.3),
        watershed_id="bagmati_001",
        bbox=BBox(south=27.5, west=85.0, north=28.0, east=85.7),
        confidence=0.87,
        agreeing_sensors=4,
        total_sensors=5,
        description="Bagmati River gauge at Chobar reading 4.2m, 3.8σ above 30-day baseline",
        source_readings=[],
        timestamp=datetime.utcnow(),
    )
    # Fire and forget
    async def _emit_task():
        await bus.emit("anomaly_alerts", alert.model_dump())

    background_tasks.add_task(_emit_task)

    return {"status": "simulation_triggered", "alert_id": alert.alert_id, "severity": "HIGH", "z_score": 3.8}


@router.get("/compound")
async def get_compound_threats() -> dict:
    """Return synthesized multi-hazard compound threats from the CompoundEventAgent."""
    state = get_state()
    threats = state.get("compound_threats", [])
    return {
        "count": len(threats),
        "threats": [t.model_dump() if hasattr(t, "model_dump") else t for t in threats[-10:]],
    }


@router.post("/chat")
async def chat_with_system(message: dict) -> dict:
    reasoner = get_reasoner()
    state = get_state()
    response = await reasoner.llm.chat(message.get("text", ""), state)
    return {"response": response}


@router.get("/sitrep")
async def get_situation_report() -> dict:
    reasoner = get_reasoner()
    state = get_state()
    sitrep = await reasoner.generate_sitrep(state)
    return {"sitrep": sitrep, "generated_at": datetime.utcnow().isoformat()}


@router.get("/reasoning")
async def get_reasoning(zone_id: str = "zone_1") -> dict:
    """Get spatial 'why' card data for a zone."""
    reasoner = get_reasoner()
    state = get_state()

    # Find zone data from urban risk reports
    feature_data: dict[str, Any] = {
        "zone_id": zone_id,
        "zone_name": zone_id.replace("_", " ").title(),
        "feature_type": "zone",
        "gauge_id": "USGS-01646500",
        "gauge_value": 4.2,
        "z_score": 3.8,
        "minutes_ago": 12,
        "soil_pct": 85,
        "soil_source": "ECMWF/CDS",
        "soil_age": "14h ago",
        "n_members_flood": 38,
        "total_members": 50,
        "depth_threshold": 0.5,
        "current_phase": str(state.get("current_phase", "00_MONITORING")),
        "phase_duration": "2h",
        "confidence": 0.76,
        "population": 12400,
        "predicted_depth_m": 2.1,
        "drainage_gap_mm": 45,
    }

    # Try to enrich from actual urban risk data
    for report in state.get("urban_risk_reports", []):
        zones = report.zones if hasattr(report, "zones") else report.get("zones", [])
        for zone in zones:
            zid = zone.zone_id if hasattr(zone, "zone_id") else zone.get("zone_id", "")
            if zid == zone_id:
                feature_data.update({
                    "zone_name": zone.zone_name if hasattr(zone, "zone_name") else zone.get("zone_name", ""),
                    "population": zone.population if hasattr(zone, "population") else zone.get("population", 0),
                    "predicted_depth_m": zone.predicted_depth_m if hasattr(zone, "predicted_depth_m") else zone.get("predicted_depth_m", 0),
                    "confidence": zone.confidence if hasattr(zone, "confidence") else zone.get("confidence", 0.5),
                })
                break

    why_card = await reasoner.generate_why_card(feature_data)
    return why_card.model_dump()
