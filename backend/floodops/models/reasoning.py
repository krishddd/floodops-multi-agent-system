"""
Shared reasoning models for the FloodOps core-3 techniques.

These Pydantic models are produced/consumed by the reusable BaseAgent
reasoning helpers (``_run_with_reflexion``, ``_ensemble_vote``,
``_quantify_uncertainty``). They follow the project convention: every model
carries ``agent_id`` + ``created_at`` and validates ``confidence`` to be a
sane probability.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UncertaintyBounds(BaseModel):
    """Epistemic (model spread) + aleatoric (data variance) bounds.

    ``epistemic_*`` captures disagreement across ensemble runs/members (what
    the model is unsure about). ``aleatoric_*`` captures irreducible
    data-driven variance. ``point`` is the central estimate.
    """

    model_config = ConfigDict(frozen=True)

    point: float
    epistemic_low: float
    epistemic_high: float
    aleatoric_low: float
    aleatoric_high: float
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def low(self) -> float:
        """Combined lower bound (widest of epistemic/aleatoric)."""
        return min(self.epistemic_low, self.aleatoric_low)

    @property
    def high(self) -> float:
        """Combined upper bound (widest of epistemic/aleatoric)."""
        return max(self.epistemic_high, self.aleatoric_high)


class ReasonedAssessment(BaseModel):
    """Generic LLM reasoning result used by the reflexion/ensemble helpers.

    Agents request this schema when they want a confidence-scored, explained
    numeric assessment (e.g. a bias-corrected flood probability or a hotspot
    risk score) instead of free text.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = "reasoning_core"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    summary: str = Field(description="Plain-language explanation of the assessment.")
    value: float = Field(description="The primary numeric assessment (e.g. probability).")
    confidence: float = Field(ge=0.0, le=1.0)
    causal_factors: list[str] = Field(
        default_factory=list,
        description="WHY this assessment holds — ranked contributing factors.",
    )
    competing_hypothesis: str | None = Field(
        default=None, description="The most credible alternative outcome."
    )

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("Confidence below 0.1 — check data quality")
        return v
