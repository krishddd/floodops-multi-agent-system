"""WebSocket handler — push live updates to all connected frontend clients."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from floodops.api.app import get_state, _app_state

router = APIRouter()
_connections: set[WebSocket] = set()

async def broadcast(message: dict) -> None:
    """Broadcast a message to all connected WebSocket clients."""
    if not _connections:
        return
    payload = json.dumps(message, default=str)
    dead = set()
    for ws in _connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    _connections -= dead

@router.websocket("/ws/flood")
async def websocket_flood(ws: WebSocket):
    """WebSocket endpoint for live flood state updates."""
    await ws.accept()
    _connections.add(ws)
    _app_state.setdefault("ws_clients", set()).add(ws)

    try:
        # Send initial state on connect
        state = get_state()
        await ws.send_json({
            "type": "initial_state",
            "data": {
                "phase": str(state.get("current_phase", "00_MONITORING")),
                "event_id": state.get("event_id", ""),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        })

        # Keep connection alive and listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat() + "Z"})
            except asyncio.TimeoutError:
                # Send heartbeat
                await ws.send_json({"type": "heartbeat", "timestamp": datetime.utcnow().isoformat() + "Z",
                                     "phase": str(get_state().get("current_phase", "00_MONITORING"))})
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)
        _app_state.get("ws_clients", set()).discard(ws)
