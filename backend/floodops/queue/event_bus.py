"""
In-memory event bus with Redis-compatible interface.

This is the central nervous system of FloodOps. All inter-agent communication
flows through this bus. Agents subscribe to named channels and receive events
asynchronously via callback. The bus also supports:

  - **emit(channel, payload)**: Publish an event to all subscribers on that channel.
  - **subscribe(channel, handler)**: Register an async callback for a channel.
  - **direct_call(target_agent, payload)**: Synchronous bypass for GLOF emergencies —
    skips the queue entirely so AlertAgent receives GLOF breach data in <100ms.
  - **register_cron(schedule, handler)**: Register a periodic task (uses asyncio scheduling,
    not real cron — in production, swap for APScheduler or Celery Beat).
  - **process_pending()**: Drain any buffered events (for testing / manual flush).

Data flow::

    SentinelAgent ──emit("anomaly_alerts")──► EventBus ──► FloodPredictAgent
                                                       ──► GLOFAgent (also CRON)
    GLOFAgent ──direct_call("alert_agent")──► AlertAgent (GLOF bypass, no queue)
    FloodPredictAgent ──emit("flood_forecasts")──► UrbanRiskAgent, AlertAgent, ResourceAgent

WebSocket broadcast hook: after every emit(), the bus calls the registered
ws_broadcast callback (if any) so the frontend gets real-time updates.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

# Type aliases for clarity
EventHandler = Callable[[str, Any], Awaitable[None]]
DirectHandler = Callable[[Any], Awaitable[Any]]
CronHandler = Callable[[], Awaitable[None]]
WSBroadcastHook = Callable[[str, Any], Awaitable[None]]


@dataclass
class PendingEvent:
    """An event waiting to be delivered to subscribers."""

    event_id: str
    channel: str
    payload: Any
    timestamp: float
    delivered: bool = False


@dataclass
class CronJob:
    """A registered periodic task."""

    job_id: str
    schedule: str  # Cron expression string (parsed externally)
    handler: CronHandler
    interval_seconds: float  # Derived from cron expression for in-memory scheduling
    last_run: float = 0.0
    task: Optional[asyncio.Task[None]] = None


class EventBus:
    """In-memory event bus with Redis-compatible semantics.

    Thread-safe for asyncio (single event loop). All operations are
    coroutines to maintain consistency even when backed by Redis later.

    Attributes:
        _subscribers: channel → list of async handlers
        _direct_handlers: agent_id → direct-call handler (for GLOF bypass)
        _cron_jobs: job_id → CronJob
        _pending: buffered events not yet delivered
        _ws_broadcast: optional WebSocket broadcast hook
        _event_history: recent events for replay (capped at 1000)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._direct_handlers: dict[str, DirectHandler] = {}
        self._cron_jobs: dict[str, CronJob] = {}
        self._pending: list[PendingEvent] = []
        self._ws_broadcast: Optional[WSBroadcastHook] = None
        self._event_history: list[PendingEvent] = []
        self._running: bool = False
        self._cron_tasks: list[asyncio.Task[None]] = []
        self._lock = asyncio.Lock()
        # Metrics (dev-only, not restart-safe — see /metrics endpoint).
        self._emit_counts: dict[str, int] = defaultdict(int)
        self._error_count: int = 0
        logger.info("EventBus initialised (in-memory mode)")

    def get_metrics(self) -> dict[str, Any]:
        """Return in-memory counters for the /metrics endpoint (dev-only)."""
        return {
            "emit_counts": dict(self._emit_counts),
            "handler_errors": self._error_count,
            "total_emits": sum(self._emit_counts.values()),
        }

    # ── Core pub/sub ─────────────────────────────────────────────────

    async def emit(self, channel: str, payload: Any) -> str:
        """Publish an event to all subscribers on a channel.

        Args:
            channel: Named channel, e.g. "anomaly_alerts", "flood_forecasts".
            payload: Any Pydantic model or dict. Subscribers receive it as-is.

        Returns:
            event_id: UUID of the published event for correlation.

        Flow:
            1. Create PendingEvent with UUID
            2. Fan-out to all channel subscribers concurrently
            3. Call WebSocket broadcast hook (if registered)
            4. Append to event history (capped)
        """
        event_id = str(uuid.uuid4())
        self._emit_counts[channel] += 1
        event = PendingEvent(
            event_id=event_id,
            channel=channel,
            payload=payload,
            timestamp=time.time(),
        )

        handlers = self._subscribers.get(channel, [])
        logger.info(
            "EventBus.emit channel=%s event_id=%s subscribers=%d",
            channel, event_id, len(handlers),
        )

        # WebSocket broadcast FIRST, non-blocking — the UI must receive live
        # events immediately and must NOT be gated on (slow or broken) agent
        # subscribers. Fire-and-forget so a stuck orchestrator can't starve the
        # frontend; errors are isolated inside _safe_ws_broadcast.
        if self._ws_broadcast is not None:
            asyncio.create_task(self._safe_ws_broadcast(channel, payload))

        # Fan-out delivery — all subscribers invoked concurrently
        if handlers:
            delivery_tasks = [
                asyncio.create_task(self._safe_deliver(handler, channel, payload))
                for handler in handlers
            ]
            await asyncio.gather(*delivery_tasks, return_exceptions=True)

        event.delivered = True

        # Record history (capped at 1000 events)
        self._event_history.append(event)
        if len(self._event_history) > 1000:
            self._event_history = self._event_history[-500:]

        return event_id

    async def _safe_ws_broadcast(self, channel: str, payload: Any) -> None:
        try:
            await self._ws_broadcast(channel, payload)  # type: ignore[misc]
        except Exception:
            logger.exception("WebSocket broadcast hook failed for channel=%s", channel)

    async def subscribe(self, channel: str, handler: EventHandler) -> None:
        """Register an async callback for a channel.

        Args:
            channel: Channel name to subscribe to.
            handler: Async function(channel: str, payload: Any) -> None.
                     The handler receives the raw payload — no envelope.

        Multiple handlers per channel are supported. A single handler
        can subscribe to multiple channels.
        """
        self._subscribers[channel].append(handler)
        logger.info(
            "EventBus.subscribe channel=%s handler=%s total=%d",
            channel, handler.__qualname__, len(self._subscribers[channel]),
        )

    async def unsubscribe(self, channel: str, handler: EventHandler) -> None:
        """Remove a specific handler from a channel."""
        if channel in self._subscribers:
            try:
                self._subscribers[channel].remove(handler)
                logger.info("EventBus.unsubscribe channel=%s handler=%s", channel, handler.__qualname__)
            except ValueError:
                pass

    # ── Direct call (GLOF bypass) ────────────────────────────────────

    def register_direct_handler(self, agent_id: str, handler: DirectHandler) -> None:
        """Register a synchronous bypass handler for an agent.

        Used by GLOF bypass: GLOFAgent calls ``direct_call("alert_agent", emergency)``
        and AlertAgent's handler is invoked immediately — no queue, no fan-out,
        no scheduling delay. This is the <100ms path for confirmed GLOF breaches
        where ``time_to_impact_minutes`` can be <30.

        Args:
            agent_id: Unique agent identifier.
            handler: Async function(payload) -> Any. Returns response directly.
        """
        self._direct_handlers[agent_id] = handler
        logger.info("EventBus.register_direct_handler agent_id=%s", agent_id)

    async def direct_call(self, target_agent: str, payload: Any) -> Any:
        """Invoke an agent's direct handler, bypassing all queues.

        This is the GLOF emergency path. Returns the handler's response
        synchronously (within the same await).

        Args:
            target_agent: Agent ID to call directly.
            payload: GLOFEmergency or similar urgent payload.

        Returns:
            Whatever the target agent's handler returns.

        Raises:
            KeyError: If no direct handler is registered for target_agent.
        """
        handler = self._direct_handlers.get(target_agent)
        if handler is None:
            raise KeyError(
                f"No direct handler registered for agent '{target_agent}'. "
                f"Available: {list(self._direct_handlers.keys())}"
            )
        logger.warning(
            "EventBus.direct_call BYPASS target=%s (GLOF emergency path)",
            target_agent,
        )
        # Also broadcast to WebSocket for real-time UI updates
        if self._ws_broadcast is not None:
            try:
                await self._ws_broadcast(f"direct_call.{target_agent}", payload)
            except Exception:
                logger.exception("WS broadcast failed during direct_call")

        return await handler(payload)

    # ── CRON scheduling ──────────────────────────────────────────────

    async def register_cron(
        self,
        schedule: str,
        handler: CronHandler,
        job_id: Optional[str] = None,
    ) -> str:
        """Register a periodic task.

        In-memory implementation uses asyncio.create_task with sleep loops.
        In production, replace with APScheduler, Celery Beat, or Cloud Scheduler.

        Args:
            schedule: Cron expression (e.g., "*/15 * * * *"). Parsed to derive
                      interval_seconds for the in-memory scheduler.
            handler: Async function() -> None invoked on each tick.
            job_id: Optional explicit job ID. Generated UUID if omitted.

        Returns:
            job_id for later cancellation.
        """
        if job_id is None:
            job_id = str(uuid.uuid4())

        interval = self._parse_cron_interval(schedule)
        job = CronJob(
            job_id=job_id,
            schedule=schedule,
            handler=handler,
            interval_seconds=interval,
        )
        self._cron_jobs[job_id] = job
        logger.info(
            "EventBus.register_cron job_id=%s schedule=%s interval=%ds",
            job_id, schedule, interval,
        )

        # Start the loop if bus is running
        if self._running:
            job.task = asyncio.create_task(self._cron_loop(job))
            self._cron_tasks.append(job.task)

        return job_id

    async def cancel_cron(self, job_id: str) -> bool:
        """Cancel a registered cron job."""
        job = self._cron_jobs.pop(job_id, None)
        if job is None:
            return False
        if job.task is not None:
            job.task.cancel()
        logger.info("EventBus.cancel_cron job_id=%s", job_id)
        return True

    # ── Pending buffer (for testing) ─────────────────────────────────

    async def process_pending(self) -> int:
        """Drain any buffered events that weren't delivered immediately.

        In normal operation, emit() delivers synchronously, so this is
        mainly useful for testing and manual flushing.

        Returns:
            Number of events processed.
        """
        async with self._lock:
            pending = [e for e in self._pending if not e.delivered]
            for event in pending:
                handlers = self._subscribers.get(event.channel, [])
                for handler in handlers:
                    await self._safe_deliver(handler, event.channel, event.payload)
                event.delivered = True
            processed = len(pending)
            self._pending = [e for e in self._pending if not e.delivered]
        if processed:
            logger.info("EventBus.process_pending processed=%d", processed)
        return processed

    # ── WebSocket hook ───────────────────────────────────────────────

    def set_ws_broadcast(self, hook: WSBroadcastHook) -> None:
        """Register the WebSocket broadcast callback.

        Called by the FastAPI lifespan to wire the WebSocket manager
        into the event bus. Every emit() then pushes to all connected
        WebSocket clients.
        """
        self._ws_broadcast = hook
        logger.info("EventBus: WebSocket broadcast hook registered")

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start all registered cron jobs."""
        self._running = True
        for job in self._cron_jobs.values():
            if job.task is None:
                job.task = asyncio.create_task(self._cron_loop(job))
                self._cron_tasks.append(job.task)
        logger.info("EventBus started with %d cron jobs", len(self._cron_jobs))

    async def stop(self) -> None:
        """Stop all cron jobs and clean up."""
        self._running = False
        for task in self._cron_tasks:
            task.cancel()
        if self._cron_tasks:
            await asyncio.gather(*self._cron_tasks, return_exceptions=True)
        self._cron_tasks.clear()
        logger.info("EventBus stopped")

    # ── Introspection ────────────────────────────────────────────────

    def get_channels(self) -> list[str]:
        """Return all channels with at least one subscriber."""
        return [ch for ch, subs in self._subscribers.items() if subs]

    def get_subscriber_count(self, channel: str) -> int:
        """Return subscriber count for a channel."""
        return len(self._subscribers.get(channel, []))

    def get_event_history(self, channel: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent events, optionally filtered by channel."""
        events = self._event_history
        if channel:
            events = [e for e in events if e.channel == channel]
        return [
            {
                "event_id": e.event_id,
                "channel": e.channel,
                "timestamp": datetime.fromtimestamp(e.timestamp).isoformat(),
                "delivered": e.delivered,
            }
            for e in events[-limit:]
        ]

    def get_cron_jobs(self) -> list[dict[str, Any]]:
        """Return info about registered cron jobs."""
        return [
            {
                "job_id": job.job_id,
                "schedule": job.schedule,
                "interval_seconds": job.interval_seconds,
                "last_run": datetime.fromtimestamp(job.last_run).isoformat() if job.last_run else None,
                "running": job.task is not None and not job.task.done(),
            }
            for job in self._cron_jobs.values()
        ]

    # ── Internal helpers ─────────────────────────────────────────────

    async def _safe_deliver(self, handler: EventHandler, channel: str, payload: Any) -> None:
        """Deliver an event to a handler with error isolation.

        On failure the error is logged AND surfaced on the ``agent_errors``
        channel so the UI/observability can see it — failures are never silently
        dropped. Recursion guard: a failure while delivering ``agent_errors``
        itself is only logged (no re-emit), so a broken error handler can't loop.
        """
        try:
            await handler(channel, payload)
        except Exception as exc:
            self._error_count += 1
            logger.exception(
                "Handler %s failed on channel=%s",
                handler.__qualname__, channel,
            )
            if channel != "agent_errors":
                try:
                    await self.emit("agent_errors", {
                        "channel": channel,
                        "handler": getattr(handler, "__qualname__", str(handler)),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Failed to emit agent_errors")

    async def _cron_loop(self, job: CronJob) -> None:
        """Run a cron job in a loop until cancelled."""
        try:
            while self._running:
                await asyncio.sleep(job.interval_seconds)
                job.last_run = time.time()
                try:
                    await job.handler()
                except Exception:
                    logger.exception("Cron job %s failed", job.job_id)
        except asyncio.CancelledError:
            logger.info("Cron job %s cancelled", job.job_id)

    @staticmethod
    def _parse_cron_interval(schedule: str) -> float:
        """Parse a cron expression into an interval in seconds.

        Handles common patterns for the in-memory scheduler:
          - ``*/N * * * *`` → every N minutes
          - ``0 */N * * *`` → every N hours
          - ``0 H */N * *`` → every N days

        For more complex expressions, defaults to 15 minutes.
        This is a simplification; production would use croniter.
        """
        parts = schedule.strip().split()
        if len(parts) != 5:
            return 900.0  # Default 15 min

        minute, hour, dom, _month, _dow = parts

        # Every N minutes: */N * * * *
        if minute.startswith("*/") and hour == "*":
            try:
                return float(int(minute[2:])) * 60
            except ValueError:
                pass

        # Every N hours: 0 */N * * *
        if minute == "0" and hour.startswith("*/"):
            try:
                return float(int(hour[2:])) * 3600
            except ValueError:
                pass

        # Every N days: 0 H */N * *
        if minute == "0" and dom.startswith("*/"):
            try:
                return float(int(dom[2:])) * 86400
            except ValueError:
                pass

        # Specific hour daily: 0 H * * *
        if minute == "0" and hour.isdigit() and dom == "*":
            return 86400.0  # Once per day

        return 900.0  # Default fallback
