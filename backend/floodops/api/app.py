"""
FastAPI application — the HTTP backbone of FloodOps.

Serves:
- REST endpoints for map layers, flood state, scenarios, ensemble data
- WebSocket for live push updates to the frontend
- OAuth callback routes for Google Workspace
- CORS middleware for the Vite frontend
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from floodops.config import FRONTEND_ORIGIN, LLM_ENSEMBLE_CONCURRENCY
from floodops.llm.client import FloodLLMClient
from floodops.llm.reasoning import FloodReasoner
from floodops.models.state import FloodSystemState, create_initial_state
from floodops.queue.event_bus import EventBus

# ── Global state (shared across routes) ──────────────────────────
# In production, this would be Redis-backed. For now, in-memory.
_app_state: dict[str, Any] = {}


def get_state() -> FloodSystemState:
    return _app_state.get("flood_state", create_initial_state())


def get_event_bus() -> EventBus:
    return _app_state.get("event_bus", EventBus())


def get_reasoner() -> FloodReasoner:
    return _app_state.get("reasoner", FloodReasoner())


def get_latest_forecast() -> dict[str, Any] | None:
    """Most recent FloodForecast dict from live state, or None (cold start)."""
    forecasts = get_state().get("flood_forecasts", [])
    if not forecasts:
        return None
    latest = forecasts[-1]
    return latest if isinstance(latest, dict) else latest.model_dump()


def get_latest_urban() -> dict[str, Any] | None:
    """Most recent UrbanRiskReport dict from live state, or None (cold start)."""
    reports = get_state().get("urban_risk_reports", [])
    if not reports:
        return None
    latest = reports[-1]
    return latest if isinstance(latest, dict) else latest.model_dump()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    # ── Startup ──────────────────────────────────────────────────
    event_bus = EventBus()
    flood_state = create_initial_state()

    # ── v4 multi-model fleet ─────────────────────────────────────
    # Heterogeneous ensemble pool: the primary provider plus the extras named
    # in LLM_ENSEMBLE_PROVIDERS (e.g. "groq,github") — distinct models vote in
    # _ensemble_vote. Every provider is wrapped in the 429-cooldown guard by
    # make_provider; an unavailable extra is simply skipped by the pool.
    from floodops.config import LLM_ENSEMBLE_PROVIDERS
    from floodops.llm.providers import make_provider

    primary = make_provider()
    extras = []
    for name in (n.strip() for n in LLM_ENSEMBLE_PROVIDERS.split(",") if n.strip()):
        p = make_provider(name)
        if p.name != primary.name and p.available():
            extras.append(p)
    llm_client = FloodLLMClient(provider=primary, extra_providers=extras)
    reasoner = FloodReasoner(llm_client)

    # Per-agent routing (free-tier friendly, no agent-code changes):
    #  * fast lane — Groq llama for the high-frequency SentinelAgent;
    #  * deep lane — GitHub Models gpt-4.1-mini for the two low-frequency deep
    #    reasoners (compound, urban), falling back to the primary when the
    #    GitHub free tier is cooling down or unkeyed.
    fast = make_provider("groq")
    fast_client = (FloodLLMClient(provider=fast, extra_providers=extras)
                   if fast.available() else llm_client)
    deep = make_provider("github")
    deep_client = (FloodLLMClient(provider=deep, extra_providers=[primary, *extras])
                   if deep.available() else llm_client)

    _app_state["event_bus"] = event_bus
    _app_state["flood_state"] = flood_state
    _app_state["llm_client"] = llm_client
    _app_state["reasoner"] = reasoner
    _app_state["ws_clients"] = set()

    # Shared LLM concurrency cap — created here (inside the running loop, after
    # config load), then installed on BaseAgent so every agent's ensemble/
    # reflexion calls are bounded. Default 1 = sequential (tier-1 RPM safe).
    from floodops.agents.base import set_agent_memory, set_llm_semaphore
    llm_semaphore = asyncio.Semaphore(LLM_ENSEMBLE_CONCURRENCY)
    _app_state["_llm_semaphore"] = llm_semaphore
    set_llm_semaphore(llm_semaphore)

    # Shared agent memory (historical-event recall). Semantic recall activates
    # only when sentence-transformers is installed (keyless); otherwise disabled.
    from floodops.llm.memory import AgentMemory
    agent_memory = AgentMemory()
    _app_state["agent_memory"] = agent_memory
    set_agent_memory(agent_memory)

    from floodops.agents.alert import AlertAgent
    from floodops.agents.compound import CompoundEventAgent
    from floodops.agents.disease import DiseaseRiskAgent
    from floodops.agents.glof import GLOFAgent
    from floodops.agents.predict import FloodPredictAgent
    from floodops.agents.resource import ResourceAgent
    from floodops.agents.sentinel import SentinelAgent
    from floodops.agents.urban import UrbanRiskAgent
    from floodops.orchestrator.service import OrchestratorService

    # Initialize Graph Orchestrator
    orchestrator = OrchestratorService(event_bus, _app_state)
    await orchestrator.initialize()
    _app_state["orchestrator"] = orchestrator

    # Keyless real-data connectors (Open-Meteo rainfall/discharge, OSM Overpass).
    # Injected into the agents that consume them; everything degrades to mock
    # generation when a source is unreachable.
    from floodops.connectors.gdacs import GDACSConnector
    from floodops.connectors.openmeteo import OpenMeteoConnector
    from floodops.connectors.osm import OSMConnector
    from floodops.connectors.reliefweb import ReliefWebConnector
    openmeteo = OpenMeteoConnector()
    osm = OSMConnector()
    gdacs = GDACSConnector()
    reliefweb = ReliefWebConnector()
    _app_state["connectors"] = {"openmeteo": openmeteo, "osm": osm,
                                "gdacs": gdacs, "reliefweb": reliefweb}

    agents = [
        SentinelAgent(event_bus=event_bus, llm=fast_client, connector=openmeteo,
                      gdacs=gdacs),
        GLOFAgent(event_bus=event_bus, llm=llm_client),
        FloodPredictAgent(event_bus=event_bus, llm=llm_client, connector=openmeteo),
        UrbanRiskAgent(event_bus=event_bus, llm=deep_client, connector=osm),
        AlertAgent(event_bus=event_bus, llm=llm_client),
        ResourceAgent(event_bus=event_bus, llm=llm_client),
        DiseaseRiskAgent(event_bus=event_bus, llm=llm_client, connector=reliefweb),
        CompoundEventAgent(event_bus=event_bus, llm=deep_client),
    ]
    for agent in agents:
        await agent.initialize()
    _app_state["agents"] = agents

    # Bridge every event-bus emit to all connected WebSocket clients so the
    # frontend receives live agent output. The bus calls the hook as
    # hook(channel, payload); we wrap it as {type: channel, data: payload}.
    from floodops.api.websocket import broadcast as ws_broadcast

    async def _ws_bridge(channel: str, payload: Any) -> None:
        await ws_broadcast({"type": channel, "data": payload})

    event_bus.set_ws_broadcast(_ws_bridge)

    fleet = [primary.name] + [p.name for p in extras]
    if fast_client is not llm_client:
        fleet.append("groq(fast-lane)")
    if deep_client is not llm_client:
        fleet.append("github(deep-lane)")
    print(f"FloodOps v4 - All {len(agents)} agents initialized "
          f"(LLM fleet: {', '.join(dict.fromkeys(fleet)) if llm_client.available() else 'mock/no-key'})")
    print("LangGraph Orchestrator hooked to Event Bus")
    print("API: http://0.0.0.0:8000")
    print(f"Frontend: {FRONTEND_ORIGIN}")

    yield

    # ── Shutdown ─────────────────────────────────────────────────
    for agent in _app_state.get("agents", []):
        if hasattr(agent, "close"):
            await agent.close()
    print("🛑 FloodOps shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from floodops.obs import setup_logging
    setup_logging()

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
    from floodops.api.routes_auth import router as auth_router
    from floodops.api.routes_ensemble import router as ensemble_router
    from floodops.api.routes_flood import router as flood_router
    from floodops.api.routes_map import router as map_router
    from floodops.api.routes_scenario import router as scenario_router
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

    @app.get("/health")
    async def health():
        """Aggregate readiness: agents, LLM, and each connector (live/mock)."""
        llm = _app_state.get("llm_client")
        agents = _app_state.get("agents", [])
        connectors = _app_state.get("connectors", {})

        conn_status: dict[str, Any] = {}
        for name, conn in connectors.items():
            try:
                ok = await asyncio.wait_for(conn.health_check(), timeout=3.0)
            except Exception:
                ok = False
            conn_status[name] = {
                "is_mock": getattr(conn, "is_mock", True),
                "reachable": bool(ok),
                "status": "mock" if getattr(conn, "is_mock", True)
                          else ("live" if ok else "error"),
            }

        return {
            "status": "ok",
            "agents": [getattr(a, "agent_id", "?") for a in agents],
            "llm_available": bool(llm and llm.available()),
            "llm_fleet": ([getattr(p, "name", "?")
                           for p in llm.provider_pool()]
                          if llm and hasattr(llm, "provider_pool") else []),
            "connectors": conn_status,
        }

    @app.get("/metrics")
    async def metrics():
        """Prometheus exposition (dev-only, in-memory counters — reset on restart)."""
        from fastapi import Response
        from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

        bus = _app_state.get("event_bus")
        reg = CollectorRegistry()
        emits = Gauge("floodops_channel_emits", "Events emitted per channel",
                      ["channel"], registry=reg)
        errors = Gauge("floodops_handler_errors_total", "Handler errors", registry=reg)
        if bus is not None:
            m = bus.get_metrics()
            for channel, count in m.get("emit_counts", {}).items():
                emits.labels(channel=channel).set(count)
            errors.set(m.get("handler_errors", 0))
        return Response(generate_latest(reg), media_type=CONTENT_TYPE_LATEST)

    return app
