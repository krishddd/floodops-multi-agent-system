"""
OrchestratorService — The engine that executes the LangGraph state machine.

Listens to EventBus queues (e.g., `flood_forecasts`), invokes the compiled 
StateGraph to advance the phase, and updates global state.
"""

import asyncio
from typing import Any

from floodops.models.state import FloodSystemState
from floodops.orchestrator.graph import compile_flood_graph
from floodops.queue.event_bus import EventBus
from floodops.api.websocket import broadcast


class OrchestratorService:
    def __init__(self, event_bus: EventBus, global_state: dict[str, Any]):
        self.event_bus = event_bus
        self.global_state = global_state
        self.graph = compile_flood_graph()
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Subscribe to events that trigger state machine advancement."""
        self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        self.event_bus.subscribe("urban_risk_reports", self.handle_urban_risk)
        self.event_bus.subscribe("alert_dispatches", self.handle_dispatch)
        self.event_bus.subscribe("glof_alerts", self.handle_glof)
        
        # Also ensure state is correctly set
        if "flood_state" not in self.global_state:
            from floodops.models.state import create_initial_state
            self.global_state["flood_state"] = create_initial_state()

    async def _step_graph(self) -> None:
        """Run the LangGraph state machine sequentially."""
        async with self._lock:
            current_state = self.global_state["flood_state"]
            
            # The LangGraph ainvoke expects the full state dictionary/object
            new_state = await self.graph.ainvoke(current_state)
            
            # Detect phase change
            old_phase = current_state.get("current_phase", "00_MONITORING")
            new_phase = new_state.get("current_phase", "00_MONITORING")
            
            self.global_state["flood_state"] = new_state

            if old_phase != new_phase:
                print(f"🔄 ORCHESTRATOR PHASE CHANGE: {old_phase} ➔ {new_phase}")
                await broadcast("heartbeat", {
                    "phase": new_phase,
                    "event_id": new_state.get("event_id", "")
                })

    async def handle_forecast(self, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        forecasts = state.get("flood_forecasts", [])
        # We need to parse or append the payload.
        # But in LangGraph, state updates are typically handled by nodes.
        # Here we just inject into global state and let the graph route based on it.
        # Wait, Pydantic objects or dicts? payload is dict.
        forecasts.append(payload)
        state["flood_forecasts"] = forecasts
        
        await self._step_graph()

    async def handle_urban_risk(self, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        reports = state.get("urban_risk_reports", [])
        reports.append(payload)
        state["urban_risk_reports"] = reports
        state["urban_mapping_complete"] = True
        
        await self._step_graph()

    async def handle_dispatch(self, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        dispatches = state.get("alert_dispatches", [])
        dispatches.append(payload)
        state["alert_dispatches"] = dispatches
        state["evacuation_routes_published"] = True
        
        await self._step_graph()

    async def handle_glof(self, payload: dict[str, Any]) -> None:
        state = self.global_state["flood_state"]
        state["is_glof_breach"] = True
        
        await self._step_graph()

