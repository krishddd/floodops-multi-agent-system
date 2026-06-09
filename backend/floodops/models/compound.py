"""
Output models for the CompoundEventAgent.

A compound event is the simultaneous co-occurrence of multiple hazards
(riverine flood, GLOF surge, landslide, disease outbreak) in the same
spatial/temporal window. The CompoundThreat fuses them into a single,
explainable threat score for an emergency commander.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from floodops.models.geo import BBox, GeoJsonGeometry
from floodops.models.reasoning import UncertaintyBounds


class ContributingHazard(BaseModel):
    """One hazard signal feeding the compound assessment."""

    model_config = ConfigDict(frozen=True)

    hazard_type: str  # "flood" | "glof" | "landslide" | "disease" | "anomaly"
    source_agent: str
    severity: float = Field(ge=0.0, le=1.0)
    detail: str = ""


class CompoundThreat(BaseModel):
    """Unified multi-hazard threat assessment for emergency command.

    Produced when ≥2 hazards co-occur in the watched window. The
    ``unified_threat_score`` is fused (ensemble-voted when an LLM is
    configured) and carries explicit uncertainty bounds plus a causal
    explanation of HOW the hazards compound.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = "compound_event_agent"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    threat_id: str
    event_id: str
    region: BBox
    hotspot: GeoJsonGeometry

    unified_threat_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: UncertaintyBounds

    contributing_hazards: list[ContributingHazard] = Field(default_factory=list)
    compounding_factors: list[str] = Field(
        default_factory=list,
        description="HOW the hazards amplify one another (causal mechanisms).",
    )
    recommended_action: str = ""
    summary: str = ""

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("Confidence below 0.1 — check data quality")
        return v
