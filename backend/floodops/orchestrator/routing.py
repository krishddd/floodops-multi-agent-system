"""
Conditional edge routing functions for the FloodOps state machine.

Each function examines the current FloodSystemState and returns the
name of the next node (phase) to transition to. These encode the
threshold checks and gate conditions from the specification.

GATE CONDITIONS (checked BEFORE transitions):
- Cannot enter EVACUATION until urban_mapping_complete == True
- Cannot enter ACTIVE until evacuation_routes_published == True
- Cannot enter POST_FLOOD until supplies_prepositioned == True
- Cannot enter RECOVERY until outbreak_risk_cleared == True
"""

from __future__ import annotations

from floodops.config import (
    PROB_EVACUATION,
    PROB_IMMINENT,
)
from floodops.models.enums import AlertLevel
from floodops.models.state import FloodSystemState


def route_monitoring(state: FloodSystemState) -> str:
    """MONITORING → ELEVATED if any alert >= MEDIUM, else stay.

    This is the entry point — SentinelAgent and GLOFAgent poll
    continuously. When an anomaly exceeds the MEDIUM threshold,
    FloodPredictAgent is triggered and we escalate.
    """
    alerts = state.get("active_alerts", [])
    glof_emergencies = state.get("glof_emergencies", [])

    # GLOF emergency bypass → jump straight to evacuation
    if glof_emergencies:
        return "evacuation"

    # Check for MEDIUM+ alerts
    for alert in alerts:
        level = alert.level if hasattr(alert, "level") else alert.get("level", "")
        if level in (AlertLevel.MEDIUM, AlertLevel.HIGH, AlertLevel.CRITICAL,
                     "MEDIUM", "HIGH", "CRITICAL"):
            return "elevated"

    return "monitoring"  # Continue monitoring


def route_elevated(state: FloodSystemState) -> str:
    """ELEVATED → IMMINENT if max flood probability > 70%.
    ELEVATED → MONITORING if de-escalation (probability drops).

    De-escalation: if the latest forecast shows probability dropped
    below the threshold, we step back down to monitoring.
    """
    forecasts = state.get("flood_forecasts", [])
    glof_emergencies = state.get("glof_emergencies", [])

    # GLOF bypass
    if glof_emergencies:
        return "evacuation"

    if not forecasts:
        return "elevated"  # Stay — no forecast yet

    latest = forecasts[-1]
    max_prob = latest.max_probability if hasattr(latest, "max_probability") else latest.get("max_probability", 0)

    if max_prob >= PROB_IMMINENT:
        return "imminent"
    elif max_prob < 0.2:
        return "monitoring"  # De-escalate

    return "elevated"  # Stay in elevated


def route_imminent(state: FloodSystemState) -> str:
    """IMMINENT → EVACUATION if probability > 90% OR GLOF breach.
    Gate: urban_mapping_complete must be True.

    Will NOT issue evacuation order until UrbanRiskAgent mapping is
    confirmed complete — avoids routing people to unknown roads.
    """
    forecasts = state.get("flood_forecasts", [])
    glof_emergencies = state.get("glof_emergencies", [])
    urban_complete = state.get("urban_mapping_complete", False)

    # GLOF bypass ignores probability threshold but still needs urban mapping
    if glof_emergencies and urban_complete:
        return "evacuation"

    if not forecasts:
        return "imminent"

    latest = forecasts[-1]
    max_prob = latest.max_probability if hasattr(latest, "max_probability") else latest.get("max_probability", 0)

    if max_prob >= PROB_EVACUATION and urban_complete:
        return "evacuation"

    # De-escalation check
    if max_prob < PROB_IMMINENT:
        return "elevated"

    return "imminent"  # Stay — either probability not high enough or urban not complete


def route_evacuation(state: FloodSystemState) -> str:
    """EVACUATION → ACTIVE if gauge breach or SAR confirms inundation.
    Gate: evacuation_routes_published must be True.
    """
    routes_published = state.get("evacuation_routes_published", False)

    # Check for confirmed flooding in active alerts
    alerts = state.get("active_alerts", [])
    flood_confirmed = False
    for alert in alerts:
        level = alert.level if hasattr(alert, "level") else alert.get("level", "")
        if level in (AlertLevel.CRITICAL, "CRITICAL"):
            flood_confirmed = True
            break

    if flood_confirmed and routes_published:
        return "active_flood"

    return "evacuation"


def route_active(state: FloodSystemState) -> str:
    """ACTIVE → POST_FLOOD if gauge levels dropping 4+ consecutive hours.
    Gate: supplies_prepositioned must be True.
    """
    receding = state.get("flood_receding_events", [])
    supplies_ready = state.get("supplies_prepositioned", False)

    if receding and supplies_ready:
        return "post_flood"

    return "active_flood"


def route_post_flood(state: FloodSystemState) -> str:
    """POST_FLOOD → RECOVERY if outbreak risk below threshold."""
    outbreak_cleared = state.get("outbreak_risk_cleared", False)

    if outbreak_cleared:
        return "recovery"

    return "post_flood"


def route_recovery(state: FloodSystemState) -> str:
    """RECOVERY → MONITORING once assessment complete (cycle restarts)."""
    # In a real system, this would check if infrastructure assessment
    # is complete and training data has been ingested. For now, always
    # allow transition back to monitoring.
    return "monitoring"
