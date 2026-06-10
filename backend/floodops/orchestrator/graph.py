"""
LangGraph state machine — the coordination brain of FloodOps.

Defines the 7-phase StateGraph with conditional edges driven by
FloodPredictAgent probability thresholds and phase completion checks.

The graph handles:
- Forward escalation (MONITORING → ELEVATED → IMMINENT → EVACUATION → ACTIVE)
- De-escalation (ELEVATED → MONITORING if probability drops)
- GLOF bypass (any phase → EVACUATION on confirmed breach)
- Gate conditions (blocks transitions until prerequisites are met)
- Compound events (multiple alerts merged into one response)
- Full audit trail (every transition logged with justification)
"""

from __future__ import annotations

from langgraph.graph import StateGraph

from floodops.models.state import FloodSystemState
from floodops.orchestrator.nodes import (
    active_flood_node,
    elevated_node,
    evacuation_node,
    imminent_node,
    monitoring_node,
    post_flood_node,
    recovery_node,
)
from floodops.orchestrator.routing import (
    route_active,
    route_elevated,
    route_evacuation,
    route_imminent,
    route_monitoring,
    route_post_flood,
    route_recovery,
)


def build_flood_graph() -> StateGraph:
    """Build the 7-phase LangGraph state machine.

    Architecture:

        ┌──────────┐    alert >= MEDIUM    ┌──────────┐
        │MONITORING├──────────────────────►│ ELEVATED │
        │  (00)    │◄──────────────────────┤  (01)    │
        └──────────┘    prob drops <20%    └────┬─────┘
             ▲                                  │ prob > 70%
             │                                  ▼
        ┌────┴─────┐                      ┌──────────┐
        │ RECOVERY │                      │ IMMINENT │
        │  (06)    │                      │  (02)    │
        └────┬─────┘                      └────┬─────┘
             ▲                                  │ prob > 90% OR GLOF
             │ risk cleared                     │ + urban_mapping_complete
        ┌────┴─────┐                      ┌────▼─────┐
        │POST_FLOOD│                      │EVACUATION│
        │  (05)    │                      │  (03)    │
        └────┬─────┘                      └────┬─────┘
             ▲                                  │ gauge breach
             │ gauge dropping 4h                │ + routes_published
        ┌────┴─────┐                      ┌────▼─────┐
        │  ACTIVE  │◄─────────────────────┤  ACTIVE  │
        │  (04)    │                      │  FLOOD   │
        └──────────┘                      └──────────┘

    GLOF BYPASS: Confirmed breach → jump directly to EVACUATION
    from ANY phase (handled in routing functions).

    Returns:
        Compiled StateGraph ready for invocation.
    """

    graph = StateGraph(FloodSystemState)

    # ── Add nodes (one per phase) ───────────────────────────────
    graph.add_node("monitoring", monitoring_node)
    graph.add_node("elevated", elevated_node)
    graph.add_node("imminent", imminent_node)
    graph.add_node("evacuation", evacuation_node)
    graph.add_node("active_flood", active_flood_node)
    graph.add_node("post_flood", post_flood_node)
    graph.add_node("recovery", recovery_node)

    # ── Set entry point ─────────────────────────────────────────
    graph.set_entry_point("monitoring")

    # ── Add conditional edges ───────────────────────────────────
    # Each routing function returns the name of the next node

    graph.add_conditional_edges("monitoring", route_monitoring, {
        "monitoring": "monitoring",   # Stay — no anomaly
        "elevated": "elevated",       # Escalate — MEDIUM+ alert
        "evacuation": "evacuation",   # GLOF bypass
    })

    graph.add_conditional_edges("elevated", route_elevated, {
        "elevated": "elevated",       # Stay — waiting for forecast
        "imminent": "imminent",       # Escalate — probability > 70%
        "monitoring": "monitoring",   # De-escalate — probability dropped
        "evacuation": "evacuation",   # GLOF bypass
    })

    graph.add_conditional_edges("imminent", route_imminent, {
        "imminent": "imminent",       # Stay — gates not met
        "evacuation": "evacuation",   # Escalate — prob > 90% + urban complete
        "elevated": "elevated",       # De-escalate — probability dropped
    })

    graph.add_conditional_edges("evacuation", route_evacuation, {
        "evacuation": "evacuation",   # Stay — waiting for confirmation
        "active_flood": "active_flood",  # Confirmed flooding
    })

    graph.add_conditional_edges("active_flood", route_active, {
        "active_flood": "active_flood",  # Stay — still flooding
        "post_flood": "post_flood",      # Water receding
    })

    graph.add_conditional_edges("post_flood", route_post_flood, {
        "post_flood": "post_flood",   # Stay — outbreak risk not cleared
        "recovery": "recovery",       # Risk cleared
    })

    graph.add_conditional_edges("recovery", route_recovery, {
        "monitoring": "monitoring",   # Cycle restarts
    })

    return graph


def compile_flood_graph():
    """Build and compile the graph for execution.

    The compiled graph can be invoked with:
        result = await compiled.ainvoke(initial_state)
    or stepped through with:
        async for state in compiled.astream(initial_state):
            print(state)
    """
    graph = build_flood_graph()
    return graph.compile()
