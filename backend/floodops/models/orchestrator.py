"""
Orchestrator data models.

The orchestrator is the LangGraph state machine that coordinates all agents.
Every state transition, every agent invocation, and every decision is
logged with full provenance in the audit trail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from floodops.models.enums import FloodPhase


class AuditEntry(BaseModel):
    """Append-only audit log entry.

    Every action in the system produces an audit entry. This is the
    full decision trail for post-event debrief and model improvement.
    The LLM generates the 'reasoning' field — grounded in actual data,
    not generic narrative.
    """

    entry_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str = Field(..., description="Which agent performed this action")
    action: str = Field(..., description="What was done: 'emit_alert', 'phase_transition', etc.")
    reasoning: str = Field(
        ...,
        description="LLM-generated justification grounded in actual sensor readings "
                    "and ensemble data. Not generic — cites specific numbers."
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Agent's confidence in this action")
    input_summary: Optional[str] = Field(None, description="What data triggered this action")
    output_summary: Optional[str] = Field(None, description="What was produced")
    data_sources: list[str] = Field(
        default_factory=list,
        description="Which data sources contributed, with cadence badges"
    )
    phase: FloodPhase = Field(..., description="System phase when this action occurred")
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateTransitionEvent(BaseModel):
    """Record of a phase transition in the state machine.

    Includes the LLM justification and what would need to happen
    for de-escalation — this is surfaced on the timeline as colored dots.
    """

    transition_id: str
    from_phase: FloodPhase
    to_phase: FloodPhase
    trigger_agent: str = Field(..., description="Agent whose output triggered this transition")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    justification: str = Field(
        ...,
        description="LLM-generated explanation of WHY this transition happened, "
                    "citing specific thresholds and data values"
    )
    deescalation_conditions: Optional[str] = Field(
        None,
        description="What would need to happen for the system to step back down"
    )
    gate_conditions_met: dict[str, bool] = Field(
        default_factory=dict,
        description="Which gate conditions were checked and their status"
    )
    was_borderline: bool = Field(
        False,
        description="True if any triggering value was within 10% of threshold"
    )


class CoordinationOrder(BaseModel):
    """Command from orchestrator to a specific agent."""

    order_id: str
    target_agent: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    deadline: Optional[datetime] = None
    priority: int = Field(1, ge=1, le=5)
    issued_at: datetime = Field(default_factory=datetime.utcnow)


class WhyCardData(BaseModel):
    """Data structure for the spatial 'why' card shown on the map.

    This is the bridge between LLM reasoning and the UI. When a user
    clicks any map feature, this model is returned with data-grounded
    explanation, confidence, competing hypotheses, and source provenance.
    """

    feature_id: str
    feature_type: str = Field(..., description="zone / lake / sensor / route")
    feature_name: str

    # LLM reasoning
    explanation: str = Field(
        ...,
        description="LLM-generated explanation citing specific numbers. "
                    "NOT 'high rainfall' but '142mm in 24h, 2.8σ above 30-day mean'."
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_explanation: str = Field("", description="Why this confidence level")

    # Ensemble disagreement (if applicable)
    majority_view: Optional[str] = Field(None, description="What most ensemble members predict")
    majority_pct: Optional[float] = Field(None, ge=0, le=1)
    minority_view: Optional[str] = Field(None, description="What dissenting members predict")
    minority_pct: Optional[float] = Field(None, ge=0, le=1)

    # Data provenance
    data_sources: list[DataSourceBadge] = Field(default_factory=list)

    # Key metrics
    metrics: dict[str, Any] = Field(default_factory=dict, description="Feature-specific numbers for display")


class DataSourceBadge(BaseModel):
    """Data source provenance for 'why' cards."""

    source_name: str
    last_reading_ago: str = Field(..., description="Human-readable: '3 min ago', '4 days ago'")
    freshness_emoji: str = Field("⚪", description="🟢 🟡 🔴 ⚪")
    cadence: str = Field(..., description="'15 min', '6-day', 'static'")


# Fix forward reference
WhyCardData.model_rebuild()
