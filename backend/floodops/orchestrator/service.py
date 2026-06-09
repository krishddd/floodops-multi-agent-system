"""
OrchestratorService — The engine that executes the LangGraph state machine.

Listens to EventBus queues (e.g., `flood_forecasts`), invokes the compiled 
StateGraph to advance the phase, and updates global state.
"""

import asyncio
import logging
from typing import Any

from floodops.models.state import FloodSystemState
from floodops.orchestrator.graph import compile_flood_graph
from floodops.queue.event_bus import EventBus
from floodops.api.websocket import broadcast

logger = logging.getLogger("floodops.orchestrator")


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

    async def _step_graph(self) -> None:
        """Advance the LangGraph state machine one step.

        NOTE: the compiled graph self-loops on the ``monitoring`` node when no
        escalation condition is met, so a full ``ainvoke`` from the entry node
        would recurse to the limit. We cap ``recursion_limit`` low and treat a
        recursion/any error as "no transition this step" — the phase simply
        stays put rather than crashing the handler. (Proper one-shot graph
        redesign is tracked separately; live streaming does not depend on it.)
        """
        async with self._lock:
            current_state = self.global_state["flood_state"]
            old_phase = current_state.get("current_phase", "00_MONITORING")
            try:
                new_state = await self.graph.ainvoke(
                    current_state, config={"recursion_limit": 12}
                )
            except Exception as exc:
                logger.warning("graph step skipped: %s", type(exc).__name__)
                return

            new_phase = new_state.get("current_phase", "00_MONITORING")
            self.global_state["flood_state"] = new_state

            if old_phase != new_phase:
                print(f"ORCHESTRATOR PHASE CHANGE: {old_phase} -> {new_phase}")
                # Single-dict envelope contract: {type, data, ts}.
                await broadcast({
                    "type": "phase_transition",
                    "data": {
                        "phase": new_phase,
                        "previous_phase": old_phase,
                        "event_id": new_state.get("event_id", ""),
                    },
                })

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

