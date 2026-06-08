"""
BaseAgent — abstract base class for all FloodOps agents.

Every agent in the system inherits from BaseAgent. This guarantees:
  1. Unique ``agent_id`` for audit-trail correlation
  2. Declared ``trigger_types`` (CRON, QUEUE, HTTP_DIRECT)
  3. Access to the shared EventBus for inter-agent communication
  4. Structured ``log_action()`` that produces AuditEntry objects
  5. ``initialize()`` lifecycle hook for wiring subscriptions

The BaseAgent does NOT contain domain logic — that lives in each
concrete agent. It provides the scaffolding so every agent integrates
with the event bus and audit system identically.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from floodops.models.enums import FloodPhase, TriggerType
from floodops.models.orchestrator import AuditEntry
from floodops.queue.event_bus import EventBus

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base for all FloodOps agents.

    Subclasses MUST implement:
        - ``agent_id`` (class attribute): unique string identifier
        - ``trigger_types`` (class attribute): set of TriggerType enums
        - ``initialize()``: wire event bus subscriptions and cron jobs
        - ``handle_event(channel, payload)``: process an incoming event

    Optional overrides:
        - ``handle_direct(payload)``: handle HTTP direct-call (GLOF bypass)
    """

    agent_id: str = "base"
    trigger_types: set[TriggerType] = set()

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._audit_buffer: list[AuditEntry] = []
        self._logger = logging.getLogger(f"floodops.agents.{self.agent_id}")

    @abstractmethod
    async def initialize(self) -> None:
        """Wire subscriptions, cron jobs, and direct handlers.

        Called once during application startup (from FastAPI lifespan).
        Implementations should call:
          - ``await self.event_bus.subscribe(channel, self.handle_event)``
          - ``self.event_bus.register_cron(schedule, self._cron_tick)``
          - ``self.event_bus.register_direct_handler(self.agent_id, self.handle_direct)``
        """
        ...

    @abstractmethod
    async def handle_event(self, channel: str, payload: Any) -> None:
        """Process an incoming event from the event bus.

        Args:
            channel: The channel the event arrived on.
            payload: The event payload (usually a Pydantic model).
        """
        ...

    async def handle_direct(self, payload: Any) -> Any:
        """Handle a direct (HTTP bypass) call.

        Override in agents that support TriggerType.HTTP_DIRECT.
        Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"Agent {self.agent_id} does not support HTTP_DIRECT calls"
        )

    # ── Audit logging ────────────────────────────────────────────────

    def log_action(
        self,
        action: str,
        reasoning: str,
        confidence: float,
        phase: FloodPhase = FloodPhase.MONITORING,
        *,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        data_sources: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AuditEntry:
        """Create a structured audit entry.

        Every agent action (anomaly detection, forecast generation, alert
        dispatch) produces an AuditEntry. These flow into the LangGraph
        state's ``audit_log`` list via the reducer (append, not overwrite).

        Args:
            action: Verb phrase: "emit_anomaly_alert", "generate_forecast", etc.
            reasoning: LLM-generated or data-grounded explanation.
            confidence: Agent's confidence in this action [0, 1].
            phase: Current system phase when action occurred.
            input_summary: What triggered this action.
            output_summary: What was produced.
            data_sources: List of data source identifiers.
            metadata: Arbitrary key-value pairs.

        Returns:
            The created AuditEntry (also buffered internally).
        """
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow(),
            agent_id=self.agent_id,
            action=action,
            reasoning=reasoning,
            confidence=confidence,
            input_summary=input_summary,
            output_summary=output_summary,
            data_sources=data_sources or [],
            phase=phase,
            metadata=metadata or {},
        )
        self._audit_buffer.append(entry)
        self._logger.info(
            "AUDIT agent=%s action=%s confidence=%.2f",
            self.agent_id, action, confidence,
        )
        return entry

    def flush_audit(self) -> list[AuditEntry]:
        """Return and clear the audit buffer.

        Called by orchestrator nodes after agent execution to collect
        audit entries into the LangGraph state.
        """
        entries = self._audit_buffer.copy()
        self._audit_buffer.clear()
        return entries

    # ── Utilities ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        triggers = ", ".join(t.value for t in self.trigger_types)
        return f"<{self.__class__.__name__} id={self.agent_id} triggers=[{triggers}]>"
