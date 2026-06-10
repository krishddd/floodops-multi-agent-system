"""
OrchestratorService — The engine that advances the FloodOps phase machine.

Listens to EventBus queues (e.g., `flood_forecasts`), evaluates a SINGLE phase
transition for the current phase, and updates global state.

Why not ``graph.ainvoke``: the compiled LangGraph's entry point is fixed to
``monitoring``, so invoking it from any phase resets the phase back to MONITORING
and then recurses on self-loops until it hits the recursion limit. Phase advance
is inherently event-driven and single-step here, so we evaluate one routing
decision per event using the same routing/node functions the graph is built from
(``compile_flood_graph`` is still called once at startup as a structural check).
"""

import asyncio
import logging
from typing import Any

from floodops.api.websocket import broadcast
from floodops.models.enums import FloodPhase
from floodops.orchestrator.graph import compile_flood_graph
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
from floodops.queue.event_bus import EventBus

logger = logging.getLogger("floodops.orchestrator")

# Phase enum → graph node name (also the key used by the routing/node tables).
_PHASE_TO_NODE: dict[FloodPhase, str] = {
    FloodPhase.MONITORING: "monitoring",
    FloodPhase.ELEVATED: "elevated",
    FloodPhase.IMMINENT: "imminent",
    FloodPhase.EVACUATION: "evacuation",
    FloodPhase.ACTIVE: "active_flood",
    FloodPhase.POST_FLOOD: "post_flood",
    FloodPhase.RECOVERY: "recovery",
}
_ROUTERS = {
    "monitoring": route_monitoring,
    "elevated": route_elevated,
    "imminent": route_imminent,
    "evacuation": route_evacuation,
    "active_flood": route_active,
    "post_flood": route_post_flood,
    "recovery": route_recovery,
}
_NODES = {
    "monitoring": monitoring_node,
    "elevated": elevated_node,
    "imminent": imminent_node,
    "evacuation": evacuation_node,
    "active_flood": active_flood_node,
    "post_flood": post_flood_node,
    "recovery": recovery_node,
}


def _node_name_for_phase(phase: Any) -> str:
    """Resolve the node key for a phase given as a FloodPhase or its str value."""
    if isinstance(phase, FloodPhase):
        return _PHASE_TO_NODE[phase]
    try:
        return _PHASE_TO_NODE[FloodPhase(phase)]
    except (ValueError, KeyError):
        return "monitoring"


class OrchestratorService:
    def __init__(self, event_bus: EventBus, global_state: dict[str, Any]):
        self.event_bus = event_bus
        self.global_state = global_state
        self.graph = compile_flood_graph()
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Subscribe to events that trigger state machine advancement.

        NOTE: ``subscribe`` is a coroutine — it MUST be awaited or the
        subscription is silently dropped (and the orchestrator never advances
        phases). Channel names must match what the agents actually emit:
        UrbanRiskAgent emits ``urban_risk``; GLOFAgent emits ``glof_emergencies``.
        """
        # Sentinel anomaly/receding feeds — these populate the state fields the
        # routing functions read (active_alerts, flood_receding_events). Without
        # them MONITORING never escalates and ACTIVE never de-escalates.
        await self.event_bus.subscribe("anomaly_alerts", self.handle_anomaly)
        await self.event_bus.subscribe("flood_receding", self.handle_receding)
        await self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        await self.event_bus.subscribe("urban_risk", self.handle_urban_risk)
        await self.event_bus.subscribe("alert_dispatches", self.handle_dispatch)
        await self.event_bus.subscribe("glof_emergencies", self.handle_glof)
        await self.event_bus.subscribe("disease_risk", self.handle_disease)
        await self.event_bus.subscribe("resource_orders", self.handle_resource)
        await self.event_bus.subscribe("compound_threats", self.handle_compound)

        # Also ensure state is correctly set
        if "flood_state" not in self.global_state:
            from floodops.models.state import create_initial_state
            self.global_state["flood_state"] = create_initial_state()

    @staticmethod
    def _apply_update(state: dict[str, Any], update: dict[str, Any]) -> None:
        """Merge a node's partial update into ``state`` honoring reducers.

        FloodSystemState list fields use ``operator.add`` (append) reducers, so
        list values returned by a node (``audit_log``, ``phase_transitions``) are
        appended; every scalar field replaces. This mirrors LangGraph's own merge
        for the fields the nodes actually return.
        """
        for key, value in update.items():
            if isinstance(value, list) and isinstance(state.get(key), list):
                state[key] = state[key] + value
            else:
                state[key] = value

    async def _step_graph(self) -> None:
        """Evaluate and apply at most one phase transition for the current phase.

        Single-step and event-driven: resolve the current phase's routing
        function, and if it selects a different node, run that node once to
        produce the state update, merge it, and broadcast the transition. A "stay"
        decision is a no-op. Errors are caught so a bad payload never crashes the
        handler (the phase simply doesn't advance).
        """
        async with self._lock:
            state = self.global_state["flood_state"]
            old_phase = state.get("current_phase", FloodPhase.MONITORING)
            node_name = _node_name_for_phase(old_phase)
            try:
                target = _ROUTERS[node_name](state)
                if target == node_name:
                    return  # No transition this step.
                update = await _NODES[target](state)
                self._apply_update(state, update)
            except Exception as exc:
                logger.warning("phase step skipped: %s: %s", type(exc).__name__, exc)
                return

            new_phase = state.get("current_phase", FloodPhase.MONITORING)
            old_val = old_phase.value if isinstance(old_phase, FloodPhase) else old_phase
            new_val = new_phase.value if isinstance(new_phase, FloodPhase) else new_phase
            if old_val != new_val:
                logger.info("orchestrator phase change: %s -> %s", old_val, new_val)
                # Single-dict envelope contract: {type, data, ts}.
                await broadcast({
                    "type": "phase_transition",
                    "data": {
                        "phase": new_val,
                        "previous_phase": old_val,
                        "event_id": state.get("event_id", ""),
                    },
                })

    async def handle_anomaly(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("active_alerts", []).append(payload)
        await self._step_graph()

    async def handle_receding(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("flood_receding_events", []).append(payload)
        await self._step_graph()

    async def handle_forecast(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("flood_forecasts", []).append(payload)
        await self._step_graph()

    async def handle_urban_risk(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("urban_risk_reports", []).append(payload)
        state["urban_mapping_complete"] = True
        await self._step_graph()

    async def handle_dispatch(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("alert_dispatches", []).append(payload)
        state["evacuation_routes_published"] = True
        await self._step_graph()

    async def handle_glof(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("glof_emergencies", []).append(payload)
        state["is_glof_breach"] = True
        await self._step_graph()

    async def handle_disease(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("disease_risk_reports", []).append(payload)
        state["outbreak_risk_cleared"] = bool(payload.get("outbreak_risk_cleared", False))
        await self._step_graph()

    async def handle_resource(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("resource_orders", []).append(payload)
        state["supplies_prepositioned"] = bool(payload.get("supplies_prepositioned", True))
        await self._step_graph()

    async def handle_compound(self, channel: str, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state.setdefault("compound_threats", []).append(payload)
        await self._step_graph()

