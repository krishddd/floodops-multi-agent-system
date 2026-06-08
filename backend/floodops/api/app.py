"""
FastAPI application — the HTTP backbone of FloodOps.

Serves:
- REST endpoints for map layers, flood state, scenarios, ensemble data
- WebSocket for live push updates to the frontend
- OAuth callback routes for Google Workspace
- CORS middleware for the Vite frontend
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from floodops.config import FRONTEND_ORIGIN
from floodops.models.state import FloodSystemState, create_initial_state
from floodops.queue.event_bus import EventBus
from floodops.llm.client import FloodLLMClient
from floodops.llm.reasoning import FloodReasoner


# ── Global state (shared across routes) ──────────────────────────
# In production, this would be Redis-backed. For now, in-memory.
_app_state: dict[str, Any] = {}


def get_state() -> FloodSystemState:
    return _app_state.get("flood_state", create_initial_state())


def get_event_bus() -> EventBus:
    return _app_state.get("event_bus", EventBus())


def get_reasoner() -> FloodReasoner:
    return _app_state.get("reasoner", FloodReasoner())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # ── Startup ──────────────────────────────────────────────────
    event_bus = EventBus()
    flood_state = create_initial_state()
    llm_client = FloodLLMClient()
    reasoner = FloodReasoner(llm_client)

    _app_state["event_bus"] = event_bus
    _app_state["flood_state"] = flood_state
    _app_state["llm_client"] = llm_client
    _app_state["reasoner"] = reasoner
    _app_state["ws_clients"] = set()

    # Initialize agents
    from floodops.agents.sentinel import SentinelAgent
    from floodops.agents.glof import GLOFAgent
    from floodops.agents.predict import FloodPredictAgent
    from floodops.agents.urban import UrbanRiskAgent
    from floodops.agents.alert import AlertAgent
    from floodops.agents.resource import ResourceAgent
    from floodops.agents.disease import DiseaseRiskAgent

    agents = [
        SentinelAgent(event_bus=event_bus),
        GLOFAgent(event_bus=event_bus),
        FloodPredictAgent(event_bus=event_bus),
        UrbanRiskAgent(event_bus=event_bus),
        AlertAgent(event_bus=event_bus),
        ResourceAgent(event_bus=event_bus),
        DiseaseRiskAgent(event_bus=event_bus),
    ]
    for agent in agents:
        await agent.initialize()
    _app_state["agents"] = agents

    print("🌊 FloodOps v3 — All 7 agents initialized")
    print(f"📡 API: http://0.0.0.0:8000")
    print(f"🗺️  Frontend: {FRONTEND_ORIGIN}")

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    for agent in _app_state.get("agents", []):
        if hasattr(agent, "close"):
            await agent.close()
    print("🛑 FloodOps shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="FloodOps v3",
        description="Multi-agent flood orchestration system — UI-first architecture",
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS for Vite frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN, "http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register route modules
    from floodops.api.routes_flood import router as flood_router
    from floodops.api.routes_map import router as map_router
    from floodops.api.routes_auth import router as auth_router
    from floodops.api.routes_scenario import router as scenario_router
    from floodops.api.routes_ensemble import router as ensemble_router
    from floodops.api.routes_timeline import router as timeline_router
    from floodops.api.websocket import router as ws_router

    app.include_router(flood_router, prefix="/api/v1/flood", tags=["Flood State"])
    app.include_router(map_router, prefix="/api/v1/map", tags=["Map Layers"])
    app.include_router(auth_router, prefix="/auth", tags=["Auth"])
    app.include_router(scenario_router, prefix="/api/v1/scenario", tags=["Scenarios"])
    app.include_router(ensemble_router, prefix="/api/v1/ensemble", tags=["Ensemble"])
    app.include_router(timeline_router, prefix="/api/v1/timeline", tags=["Timeline"])
    app.include_router(ws_router, tags=["WebSocket"])

    @app.get("/")
    async def root():
        return {"service": "FloodOps v3", "status": "running", "phase": get_state().get("current_phase", "MONITORING")}

    return app
