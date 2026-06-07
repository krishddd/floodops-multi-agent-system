"""
FloodOps event bus package.

Provides the in-memory event bus with Redis-compatible interface that
wires all agents together. Agents never import each other — they only
know about the event bus and the shared models.
"""

from floodops.queue.event_bus import EventBus

__all__ = ["EventBus"]
