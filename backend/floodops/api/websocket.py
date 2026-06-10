"""WebSocket handler — push live updates to all connected frontend clients."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from floodops.api.app import _app_state, get_state

router = APIRouter()
_connections: set[WebSocket] = set()

def _envelope(message: dict) -> dict:
    """Ensure every outbound message carries {type, data, ts}."""
    msg = dict(message)
    msg.setdefault("ts", datetime.utcnow().isoformat() + "Z")
    return msg


async def broadcast(message: dict) -> None:
    """Broadcast a single typed message ``{type, data, ts}`` to all clients.

    NOTE: takes exactly one dict (not channel + payload). The event-bus→WS
    bridge in api/app.py wraps every channel as ``{type: channel, data: payload}``;
    the orchestrator wraps phase changes the same way. This is the single contract.
    """
    if not _connections:
        return
    payload = json.dumps(_envelope(message), default=str)
    dead = set()
    for ws in list(_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    # Mutate in place — rebinding (`-=`) would make `_connections` a function
    # local and raise UnboundLocalError on the read above.
    _connections.difference_update(dead)


def _snapshot() -> dict:
    """Full hydration payload sent on (re)connect so a client can resync."""
    state = get_state()
    forecasts = state.get("flood_forecasts", [])
    latest = forecasts[-1] if forecasts else None
    if latest is not None and hasattr(latest, "model_dump"):
        latest = latest.model_dump()
    threats = state.get("compound_threats", [])
    threats = [t.model_dump() if hasattr(t, "model_dump") else t for t in threats[-5:]]
    return {
        "phase": str(state.get("current_phase", "00_MONITORING")),
        "event_id": state.get("event_id", ""),
        "gate_conditions": {
            "urban_mapping_complete": state.get("urban_mapping_complete", False),
            "evacuation_routes_published": state.get("evacuation_routes_published", False),
            "supplies_prepositioned": state.get("supplies_prepositioned", False),
            "outbreak_risk_cleared": state.get("outbreak_risk_cleared", False),
        },
        "latest_forecast": {
            "max_probability": (latest or {}).get("max_probability"),
            "summary": (latest or {}).get("summary"),
        } if latest else None,
        "compound_threats": threats,
        "counts": {
            "flood_forecasts": len(forecasts),
            "compound_threats": len(state.get("compound_threats", [])),
            "alert_dispatches": len(state.get("alert_dispatches", [])),
        },
    }

@router.websocket("/ws/flood")
async def websocket_flood(ws: WebSocket):
    """WebSocket endpoint for live flood state updates.

    v4 auth: when FLOODOPS_API_KEY is set the upgrade must carry
    ``?api_key=…`` (browsers cannot set custom headers on WebSocket()); the
    connection is closed with 1008 (policy violation) otherwise.
    """
    from floodops.config import FLOODOPS_API_KEY
    if FLOODOPS_API_KEY and ws.query_params.get("api_key") != FLOODOPS_API_KEY:
        await ws.close(code=1008)
        return
    await ws.accept()
    _connections.add(ws)
    _app_state.setdefault("ws_clients", set()).add(ws)

    try:
        # Send a full snapshot on connect so a reconnecting client can resync.
        # Use send_text + default=str — the snapshot embeds Pydantic models with
        # datetime fields that ws.send_json (plain json.dumps) can't serialize.
        await ws.send_text(
            json.dumps(_envelope({"type": "initial_state", "data": _snapshot()}), default=str)
        )

        # Keep connection alive and listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat() + "Z"})
            except TimeoutError:
                # Send heartbeat
                await ws.send_json({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat() + "Z",
                                     "phase": str(get_state().get("current_phase", "00_MONITORING"))})
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)
        _app_state.get("ws_clients", set()).discard(ws)
