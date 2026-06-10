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
from typing import Any, TypeVar

from floodops.config import (
    LLM_CONFIDENCE_FLOOR,
    LLM_ENSEMBLE_RUNS,
    LLM_REFLEXION_MAX_RETRIES,
    LLM_REFLEXION_TOTAL_TIMEOUT_SECONDS,
    LLM_TIMEOUT_SECONDS,
)
from floodops.models.enums import FloodPhase, TriggerType
from floodops.models.orchestrator import AuditEntry
from floodops.models.reasoning import UncertaintyBounds
from floodops.queue.event_bus import EventBus

logger = logging.getLogger(__name__)

# Shared, lazily-initialised concurrency cap across ALL agents' LLM calls.
# Created in the FastAPI lifespan (see api/app.py) via set_llm_semaphore() so it
# binds to the running event loop and reads config at startup, not import time.
# When None (unit tests / no lifespan), reasoning runs unbounded.
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def set_llm_semaphore(sem: asyncio.Semaphore | None) -> None:
    """Install the shared LLM concurrency semaphore (called from the lifespan)."""
    global _LLM_SEMAPHORE
    _LLM_SEMAPHORE = sem


# Shared agent-memory store (historical-event recall), installed in the lifespan.
# None until installed; recall is a no-op without it. Dev-only / not restart-safe.
_AGENT_MEMORY: Any = None


def set_agent_memory(memory: Any) -> None:
    """Install the shared AgentMemory (called from the lifespan)."""
    global _AGENT_MEMORY
    _AGENT_MEMORY = memory


class _NullCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _llm_slot() -> Any:
    """Acquire the shared semaphore if installed, else a no-op context."""
    return _LLM_SEMAPHORE if _LLM_SEMAPHORE is not None else _NullCtx()

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

    def __init__(
        self,
        event_bus: EventBus,
        llm: FloodLLMClient | None = None,
        connector: Any = None,
    ) -> None:
        self.event_bus = event_bus
        self.llm = llm  # optional — None means deterministic mock fallbacks
        self.connector = connector  # optional data connector (keyless real data)
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

    async def _analyze(self, **kwargs: Any) -> Any:
        """Single structured LLM call, bounded by the shared semaphore + a
        per-call timeout. Returns None on timeout/error so callers fall back."""
        try:
            async with _llm_slot():
                return await asyncio.wait_for(
                    self.llm.analyze(**kwargs),  # type: ignore[union-attr]
                    timeout=LLM_TIMEOUT_SECONDS,
                )
        except Exception as exc:  # timeout, rate limit, malformed response, …
            self._logger.warning("LLM analyze failed/timed out: %s", exc)
            return None

    async def _critique(self, result: Any) -> str:
        try:
            async with _llm_slot():
                return await asyncio.wait_for(
                    self.llm.critique(result),  # type: ignore[union-attr]
                    timeout=LLM_TIMEOUT_SECONDS,
                )
        except Exception as exc:
            self._logger.warning("LLM critique failed/timed out: %s", exc)
            return ""

    async def _run_with_reflexion(
        self,
        system: str,
        data: Any,
        context: dict[str, Any] | None,
        schema: type[_T],
        mock: _T,
        *,
        floor: float = LLM_CONFIDENCE_FLOOR,
        max_retries: int = LLM_REFLEXION_MAX_RETRIES,
    ) -> _T:
        """Reflexion loop: analyze → self-critique → retry on low confidence.

        Returns the first assessment whose ``confidence >= floor`` (or the last
        attempt). Falls back to ``mock`` when no LLM is configured, on any
        per-call timeout/error, or if the whole loop exceeds
        ``LLM_REFLEXION_TOTAL_TIMEOUT_SECONDS`` (prevents event-loop starvation).
        """
        if not self._llm_ready():
            return mock
        try:
            return await asyncio.wait_for(
                self._reflexion_loop(system, data, context, schema, mock, floor, max_retries),
                timeout=LLM_REFLEXION_TOTAL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            self._logger.warning("Reflexion loop exceeded total budget: %s", exc)
            return mock

    async def _reflexion_loop(
        self, system, data, context, schema, mock, floor, max_retries
    ) -> _T:
        result = mock
        work_data = data
        for attempt in range(max_retries):
            out = await self._analyze(
                system=system, data=work_data, context=context, output_schema=schema
            )
            if out is None:
                return mock
            result = out
            confidence = float(getattr(out, "confidence", 0.0) or 0.0)
            if confidence >= floor or attempt == max_retries - 1:
                return result
            critique = await self._critique(out)
            work_data = {"prior_analysis": _as_dict(out), "critique": critique,
                         "original": data}
        return result

    async def _ensemble_vote(
        self,
        system: str,
        data: Any,
        context: dict[str, Any] | None,
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

        # Each _analyze acquires the shared semaphore (bounded concurrency) and
        # is per-call-timeout protected; failures resolve to None and are dropped.
        tasks = [
            self._analyze(system=system, data=data, context=context, output_schema=schema)
            for _ in range(max(1, runs))
        ]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results = [r for r in gathered if r is not None and not isinstance(r, Exception)]
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

    # ── Agent memory (historical-event recall) ───────────────────────

    def remember(self, summary: str, metadata: dict[str, Any] | None = None) -> None:
        """Store an event summary in the shared memory (no-op if disabled)."""
        if _AGENT_MEMORY is not None:
            _AGENT_MEMORY.remember(self.agent_id, summary, metadata)

    def recall_similar(self, query: str, k: int = 3) -> list[Any]:
        """Recall up to k semantically-similar past events ([] if disabled)."""
        if _AGENT_MEMORY is not None:
            return _AGENT_MEMORY.recall_similar(query, k)
        return []

    def _quantify_uncertainty(
        self,
        samples: list[float],
        *,
        ensemble_spread: list[float] | None = None,
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
        input_summary: str | None = None,
        output_summary: str | None = None,
        data_sources: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
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
