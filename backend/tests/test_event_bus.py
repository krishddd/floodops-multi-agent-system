"""Event-bus delivery tests — guards the Phase-0 handler-signature contract.

The bus delivers events as ``handler(channel, payload)`` (two args). A handler
written with a single positional arg (the original latent bug) would raise
TypeError the moment an event flowed. These tests pin the 2-arg contract.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_subscribe_delivers_channel_and_payload(event_bus):
    received: list[tuple[str, dict]] = []

    async def handler(channel, payload):
        received.append((channel, payload))

    await event_bus.subscribe("anomaly_alerts", handler)
    await event_bus.emit("anomaly_alerts", {"alert_id": "a1"})

    assert received == [("anomaly_alerts", {"alert_id": "a1"})]


@pytest.mark.asyncio
async def test_single_arg_handler_is_isolated_not_fatal(event_bus, caplog):
    """A buggy 1-arg handler must not crash emit (errors are isolated)."""
    delivered = []

    async def bad_handler(payload):  # missing channel arg — the original bug
        delivered.append(payload)

    async def good_handler(channel, payload):
        delivered.append((channel, payload))

    await event_bus.subscribe("flood_forecasts", bad_handler)
    await event_bus.subscribe("flood_forecasts", good_handler)
    # emit must not raise even though bad_handler will TypeError internally
    await event_bus.emit("flood_forecasts", {"x": 1})

    # good_handler still received its event despite the sibling failing
    assert ("flood_forecasts", {"x": 1}) in delivered


@pytest.mark.asyncio
async def test_ws_broadcast_hook_receives_emits(event_bus):
    seen = []

    async def hook(channel, payload):
        seen.append(channel)

    event_bus.set_ws_broadcast(hook)
    await event_bus.emit("urban_risk", {"z": 1})
    assert "urban_risk" in seen
