"""
FloodSystemState — the LangGraph global state.

This is the single source of truth for the entire system. The orchestrator's
state machine reads and writes this object. All agents contribute to it
via LangGraph's annotated reducer pattern (list fields APPEND, not overwrite).

IMPORTANT: This is a TypedDict (not a Pydantic model) because LangGraph
requires TypedDict for state. Pydantic models are used for the items
INSIDE the lists.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Optional, TypedDict

from floodops.models.enums import FloodPhase
from floodops.models.sentinel import AnomalyAlert, FloodRecedingEvent
from floodops.models.glof import LakeHealthReport, GLOFEmergency
from floodops.models.predict import FloodForecast
from floodops.models.urban import UrbanRiskReport
from floodops.models.alert import AlertDispatch
from floodops.models.resource import ResourceOrders
from floodops.models.disease import DiseaseRiskReport
from floodops.models.orchestrator import AuditEntry, StateTransitionEvent


class FloodSystemState(TypedDict, total=False):
    """LangGraph global state for the FloodOps orchestrator.

    KEY DESIGN DECISIONS:

    1. All list fields use Annotated[list[T], operator.add] — LangGraph's
       reducer pattern that APPENDS new items rather than overwriting.
       This means agents can return partial updates like:
       { "active_alerts": [new_alert] }
       and it gets appended to the existing list.

    2. Gate conditions are boolean flags checked BEFORE phase transitions:
       - Cannot enter EVACUATION until urban_mapping_complete == True
       - Cannot enter ACTIVE until evacuation_routes_published == True
       - Cannot enter POST_FLOOD until supplies_prepositioned == True

    3. event_id is a UUID generated on escalation from MONITORING → ELEVATED.
       All agents tag their outputs with this ID for correlation.

    4. Timeline frames are stored for scrubber playback — the frontend
       requests historical frames to animate the event development.
    """

    # ── Phase tracking ──────────────────────────────────────────────
    current_phase: FloodPhase
    previous_phase: Optional[FloodPhase]
    phase_entered_at: Optional[str]  # ISO datetime string
    event_id: str  # UUID generated on MONITORING → ELEVATED

    # ── Agent outputs (accumulated via reducers) ────────────────────
    # Each field appends new items — agents return partial updates
    active_alerts: Annotated[list[AnomalyAlert], operator.add]
    glof_reports: Annotated[list[LakeHealthReport], operator.add]
    glof_emergencies: Annotated[list[GLOFEmergency], operator.add]
    flood_forecasts: Annotated[list[FloodForecast], operator.add]
    urban_risk_reports: Annotated[list[UrbanRiskReport], operator.add]
    resource_orders: Annotated[list[ResourceOrders], operator.add]
    disease_risk_reports: Annotated[list[DiseaseRiskReport], operator.add]
    alert_dispatches: Annotated[list[AlertDispatch], operator.add]
    flood_receding_events: Annotated[list[FloodRecedingEvent], operator.add]

    # ── Gate conditions ─────────────────────────────────────────────
    # The orchestrator WILL NOT transition phases until these are True
    urban_mapping_complete: bool     # Required before EVACUATION
    evacuation_routes_published: bool  # Required before ACTIVE
    supplies_prepositioned: bool     # Required before POST_FLOOD
    outbreak_risk_cleared: bool      # Required before RECOVERY

    # ── Audit trail ─────────────────────────────────────────────────
    audit_log: Annotated[list[AuditEntry], operator.add]
    phase_transitions: Annotated[list[StateTransitionEvent], operator.add]

    # ── Timeline state (for scrubber) ───────────────────────────────
    # Stores snapshots keyed by ISO timestamp for frontend playback
    timeline_cursor: Optional[str]  # Current time position in timeline


def create_initial_state(event_id: str = "system-init") -> FloodSystemState:
    """Create the initial state for a new system instance.

    Starts in MONITORING phase with all gate conditions False
    and all agent output lists empty.
    """
    return FloodSystemState(
        current_phase=FloodPhase.MONITORING,
        previous_phase=None,
        phase_entered_at=datetime.utcnow().isoformat(),
        event_id=event_id,
        active_alerts=[],
        glof_reports=[],
        glof_emergencies=[],
        flood_forecasts=[],
        urban_risk_reports=[],
        resource_orders=[],
        disease_risk_reports=[],
        alert_dispatches=[],
        flood_receding_events=[],
        urban_mapping_complete=False,
        evacuation_routes_published=False,
        supplies_prepositioned=False,
        outbreak_risk_cleared=False,
        audit_log=[],
        phase_transitions=[],
        timeline_cursor=None,
    )
