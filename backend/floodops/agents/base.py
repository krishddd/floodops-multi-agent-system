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

import asyncio
import logging
import statistics
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional, TypeVar

from floodops.config import (
    LLM_CONFIDENCE_FLOOR,
    LLM_ENSEMBLE_RUNS,
    LLM_REFLEXION_MAX_RETRIES,
)
from floodops.models.enums import FloodPhase, TriggerType
from floodops.models.orchestrator import AuditEntry
from floodops.models.reasoning import ReasonedAssessment, UncertaintyBounds
from floodops.queue.event_bus import EventBus

logger = logging.getLogger(__name__)

# Forward-declared to avoid a hard import cycle (client imports nothing here).
try:  # pragma: no cover - typing convenience
    from floodops.llm.client import FloodLLMClient
except Exception:  # pragma: no cover
    FloodLLMClient = Any  # type: ignore

_T = TypeVar("_T")


def _as_dict(payload: Any) -> dict[str, Any]:
    """Normalize an event payload to a plain dict.

    EventBus payloads may arrive as either a Pydantic model (when an agent
    emits the model directly) or a dict (when an agent emits ``.model_dump()``).
    Handlers call ``.get(...)``, so coerce to dict defensively.
    """
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        try:
            return payload.model_dump()
        except Exception:  # pragma: no cover - defensive
            pass
    if payload is None:
        return {}
    # Last resort: shallow attribute scrape
    return dict(getattr(payload, "__dict__", {}) or {})


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

    def __init__(self, event_bus: EventBus, llm: Optional["FloodLLMClient"] = None) -> None:
        self.event_bus = event_bus
        self.llm = llm  # optional — None means deterministic mock fallbacks
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

    # ── Core-3 reasoning helpers (shared by all agents) ──────────────
    #
    # Each helper degrades gracefully: with no LLM configured (self.llm is
    # None or self.llm.available() is False), it returns the caller-supplied
    # ``mock`` value so existing deterministic behaviour is preserved.

    def _llm_ready(self) -> bool:
        return self.llm is not None and self.llm.available()

    async def _run_with_reflexion(
        self,
        system: str,
        data: Any,
        context: Optional[dict[str, Any]],
        schema: type[_T],
        mock: _T,
        *,
        floor: float = LLM_CONFIDENCE_FLOOR,
        max_retries: int = LLM_REFLEXION_MAX_RETRIES,
    ) -> _T:
        """Reflexion loop: analyze → self-critique → retry on low confidence.

        Returns the first assessment whose ``confidence >= floor`` (or the last
        attempt). Falls back to ``mock`` when no LLM is configured.
        """
        if not self._llm_ready():
            return mock

        result = mock
        work_data = data
        for attempt in range(max_retries):
            out = await self.llm.analyze(  # type: ignore[union-attr]
                system=system, data=work_data, context=context, output_schema=schema
            )
            if out is None:
                return mock
            result = out
            confidence = float(getattr(out, "confidence", 0.0) or 0.0)
            if confidence >= floor or attempt == max_retries - 1:
                return result
            critique = await self.llm.critique(out)  # type: ignore[union-attr]
            work_data = {"prior_analysis": _as_dict(out), "critique": critique,
                         "original": data}
        return result

    async def _ensemble_vote(
        self,
        system: str,
        data: Any,
        context: Optional[dict[str, Any]],
        schema: type[_T],
        mock: _T,
        *,
        runs: int = LLM_ENSEMBLE_RUNS,
    ) -> _T:
        """3-run consensus for high-stakes numeric predictions.

        Runs ``runs`` independent analyses concurrently and returns the median
        ``value``/``confidence`` member. Falls back to ``mock`` with no LLM.
        """
        if not self._llm_ready():
            return mock

        tasks = [
            self.llm.analyze(  # type: ignore[union-attr]
                system=system, data=data, context=context, output_schema=schema
            )
            for _ in range(max(1, runs))
        ]
        results = [r for r in await asyncio.gather(*tasks, return_exceptions=False) if r]
        results = [r for r in results if r is not None]
        if not results:
            return mock
        # Consensus = member nearest the median 'value' (fallback: 'confidence').
        def _num(r: Any) -> float:
            for attr in ("value", "confidence", "max_probability"):
                v = getattr(r, attr, None)
                if isinstance(v, (int, float)):
                    return float(v)
            return 0.0

        values = sorted(_num(r) for r in results)
        median_val = statistics.median(values)
        consensus = min(results, key=lambda r: abs(_num(r) - median_val))
        return consensus

    def _quantify_uncertainty(
        self,
        samples: list[float],
        *,
        ensemble_spread: Optional[list[float]] = None,
    ) -> UncertaintyBounds:
        """Epistemic (model spread) + aleatoric (data variance) bounds.

        Pure-Python — works with no LLM key by consuming the existing mock
        ensemble spread. ``samples`` is the data-driven distribution (aleatoric);
        ``ensemble_spread`` is optional model-disagreement values (epistemic).
        """
        if not samples:
            return UncertaintyBounds(
                point=0.0, epistemic_low=0.0, epistemic_high=0.0,
                aleatoric_low=0.0, aleatoric_high=0.0, confidence=0.1,
            )
        point = statistics.median(samples)
        a_sd = statistics.pstdev(samples) if len(samples) > 1 else 0.0
        spread = ensemble_spread if ensemble_spread else samples
        e_sd = statistics.pstdev(spread) if len(spread) > 1 else 0.0
        # Confidence shrinks as relative spread grows (1 - CoV, clamped).
        scale = abs(point) if abs(point) > 1e-9 else 1.0
        cov = (a_sd + e_sd) / scale
        confidence = max(0.1, min(1.0, 1.0 - cov))
        return UncertaintyBounds(
            point=round(point, 4),
            epistemic_low=round(point - 1.96 * e_sd, 4),
            epistemic_high=round(point + 1.96 * e_sd, 4),
            aleatoric_low=round(point - 1.96 * a_sd, 4),
            aleatoric_high=round(point + 1.96 * a_sd, 4),
            confidence=round(confidence, 3),
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
