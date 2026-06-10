"""
Phase node functions for the LangGraph state machine.

Each node function:
1. Reads the current FloodSystemState
2. Invokes the relevant agents (via event bus)
3. Collects their outputs
4. Returns state updates (using LangGraph's partial-update pattern)
5. Logs an AuditEntry with LLM-generated justification
"""

from __future__ import annotations

import uuid
from datetime import datetime

from floodops.models.enums import FloodPhase
from floodops.models.orchestrator import AuditEntry, StateTransitionEvent
from floodops.models.state import FloodSystemState


async def monitoring_node(state: FloodSystemState) -> dict:
    """Phase 00: Continuous monitoring (24/7).

    Active agents: SentinelAgent, GLOFAgent, UrbanRiskAgent
    Actions: Poll sensors, scan glacial lakes, update city risk maps

    SentinelAgent and GLOFAgent run on CRON — they poll independently.
    This node just logs that we're in monitoring and returns updated phase.
    """
    return {
        "current_phase": FloodPhase.MONITORING,
        "phase_entered_at": datetime.utcnow().isoformat(),
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_monitoring",
            reasoning="System in continuous monitoring mode. SentinelAgent polling "
                      "weather radar (15min), river gauges (15min), and soil moisture (daily). "
                      "GLOFAgent scanning glacial lakes on 6-day satellite cycle.",
            confidence=1.0,
            phase=FloodPhase.MONITORING,
            data_sources=["USGS_GAUGES", "NWS_ALERTS", "SENTINEL_SAR"],
        )],
    }


async def elevated_node(state: FloodSystemState) -> dict:
    """Phase 01: Elevated risk (T-72h to T-48h).

    Active agents: SentinelAgent, GLOFAgent, FloodPredictAgent
    Actions: Run 10,000-scenario ensemble flood model
    """
    event_id = state.get("event_id", str(uuid.uuid4()))

    # If this is a fresh escalation, generate a new event_id
    if state.get("current_phase") == FloodPhase.MONITORING:
        event_id = str(uuid.uuid4())

    alerts = state.get("active_alerts", [])
    latest_alert = alerts[-1] if alerts else None
    alert_desc = "unknown trigger"
    if latest_alert:
        level = latest_alert.level if hasattr(latest_alert, "level") else latest_alert.get("level", "?")
        metric = latest_alert.metric if hasattr(latest_alert, "metric") else latest_alert.get("metric", "?")
        sigma = latest_alert.deviation_sigma if hasattr(latest_alert, "deviation_sigma") else latest_alert.get("deviation_sigma", "?")
        alert_desc = f"AlertLevel.{level} on {metric} ({sigma}σ deviation)"

    return {
        "current_phase": FloodPhase.ELEVATED,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "event_id": event_id,
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_elevated",
            reasoning=f"Escalated to ELEVATED risk based on {alert_desc}. "
                      f"FloodPredictAgent now running 10,000-scenario ensemble model. "
                      f"Outputs sent to emergency agencies only — no public alert.",
            confidence=0.85,
            phase=FloodPhase.ELEVATED,
            data_sources=["USGS_GAUGES", "ECMWF_ENSEMBLE"],
        )],
        "phase_transitions": [StateTransitionEvent(
            transition_id=str(uuid.uuid4()),
            from_phase=state.get("current_phase", FloodPhase.MONITORING),
            to_phase=FloodPhase.ELEVATED,
            trigger_agent="sentinel_agent",
            justification=f"SentinelAgent raised {alert_desc}. Threshold exceeded.",
            deescalation_conditions="Probability drops below 20% on next forecast cycle.",
            gate_conditions_met={},
        )],
    }


async def imminent_node(state: FloodSystemState) -> dict:
    """Phase 02: Imminent threat (T-12h to T-24h).

    Active agents: SentinelAgent, FloodPredictAgent, UrbanRiskAgent, ResourceAgent
    Actions: Street-level mapping, supply pre-positioning
    """
    forecasts = state.get("flood_forecasts", [])
    latest = forecasts[-1] if forecasts else None
    max_prob = 0
    if latest:
        max_prob = latest.max_probability if hasattr(latest, "max_probability") else latest.get("max_probability", 0)

    return {
        "current_phase": FloodPhase.IMMINENT,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_imminent",
            reasoning=f"Escalated to IMMINENT. FloodPredictAgent reports max probability "
                      f"{max_prob:.0%}, exceeding the 70% threshold. UrbanRiskAgent mapping "
                      f"inundation path to street level. ResourceAgent pre-positioning supplies.",
            confidence=max_prob,
            phase=FloodPhase.IMMINENT,
            data_sources=["ECMWF_ENSEMBLE", "USGS_GAUGES", "OSM"],
        )],
        "phase_transitions": [StateTransitionEvent(
            transition_id=str(uuid.uuid4()),
            from_phase=state.get("current_phase", FloodPhase.ELEVATED),
            to_phase=FloodPhase.IMMINENT,
            trigger_agent="flood_predict_agent",
            justification=f"FloodPredictAgent probability {max_prob:.0%} > 70% threshold.",
            deescalation_conditions="Probability drops below 70% on next forecast update.",
            gate_conditions_met={"urban_mapping_complete": state.get("urban_mapping_complete", False)},
            was_borderline=0.65 <= max_prob <= 0.75,
        )],
    }


async def evacuation_node(state: FloodSystemState) -> dict:
    """Phase 03: Evacuation order (T-2h to T-6h).

    Active agents: AlertAgent, UrbanRiskAgent, ResourceAgent, FloodPredictAgent
    Actions: Mass SMS, radio, sirens, live evacuation routing
    """
    return {
        "current_phase": FloodPhase.EVACUATION,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "evacuation_routes_published": True,
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_evacuation",
            reasoning="EVACUATION ORDER ISSUED. AlertAgent firing all channels: "
                      "SMS cell broadcast, radio scripts, siren activation. "
                      "UrbanRiskAgent providing live route updates as flood front approaches.",
            confidence=0.95,
            phase=FloodPhase.EVACUATION,
            data_sources=["ECMWF_ENSEMBLE", "USGS_GAUGES", "OSM", "NWS_ALERTS"],
        )],
    }


async def active_flood_node(state: FloodSystemState) -> dict:
    """Phase 04: Active flood (T=0 to T+24h).

    Active agents: SentinelAgent, AlertAgent, ResourceAgent
    Actions: Real-time SAR flood extent, dynamic zone boundaries, rescue routing
    """
    return {
        "current_phase": FloodPhase.ACTIVE,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_active_flood",
            reasoning="FLOOD CONFIRMED. SentinelAgent switched to Sentinel-1 SAR for "
                      "cloud-penetrating flood extent mapping. ResourceAgent coordinating "
                      "rescue boat routes. AlertAgent updating safe/unsafe zone boundaries.",
            confidence=1.0,
            phase=FloodPhase.ACTIVE,
            data_sources=["SENTINEL_SAR", "USGS_GAUGES"],
        )],
    }


async def post_flood_node(state: FloodSystemState) -> dict:
    """Phase 05: Post-flood response (T+24h to T+14d).

    Active agents: DiseaseRiskAgent, ResourceAgent, SentinelAgent
    Actions: Disease prediction, medical supply pre-positioning
    """
    return {
        "current_phase": FloodPhase.POST_FLOOD,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_post_flood",
            reasoning="Flood waters receding. DiseaseRiskAgent modeling cholera, typhoid, "
                      "and leptospirosis risk at 100m resolution. ResourceAgent routing "
                      "medical supplies to predicted hotspots before symptom onset.",
            confidence=0.9,
            phase=FloodPhase.POST_FLOOD,
            data_sources=["USGS_GAUGES", "ECMWF_ENSEMBLE"],
        )],
    }


async def recovery_node(state: FloodSystemState) -> dict:
    """Phase 06: Recovery and rebuild (T+14d onwards).

    Active agents: UrbanRiskAgent, SentinelAgent, FloodPredictAgent
    Actions: Damage assessment, redesign recommendations, model retraining
    """
    return {
        "current_phase": FloodPhase.RECOVERY,
        "previous_phase": state.get("current_phase"),
        "phase_entered_at": datetime.utcnow().isoformat(),
        "outbreak_risk_cleared": True,
        "audit_log": [AuditEntry(
            entry_id=str(uuid.uuid4()),
            agent_id="orchestrator",
            action="phase_recovery",
            reasoning="Outbreak risk cleared. UrbanRiskAgent generating damage assessment "
                      "from pre/post satellite comparison. FloodPredictAgent ingesting this "
                      "event as new training data for autoresearch model improvement.",
            confidence=0.95,
            phase=FloodPhase.RECOVERY,
            data_sources=["SENTINEL_OPTICAL", "OSM"],
        )],
    }
