"""
FloodPredictAgent data models.

FloodPredictAgent is the probabilistic engine — it converts sensor anomalies
into spatial probability estimates by running 10,000 Monte Carlo scenarios
through watershed hydraulic models.

CRITICAL FOR UI: The ensemble is the richest data in the system. Instead of
collapsing 50 ECMWF members to a single "max probability", we preserve the
full spread for visualization — spaghetti plots, probability fans, and
disagreement badges all come from these models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from floodops.models.geo import BBox, GeoJsonGeometry, GeoJsonFeatureCollection


class FloodScenario(BaseModel):
    """A single Monte Carlo scenario result.

    One of ~10,000 scenarios generated per event. Each scenario samples
    from weather uncertainty × soil moisture uncertainty and routes
    rainfall through the watershed DEM.
    """

    scenario_id: int
    ensemble_member_id: int = Field(..., description="ECMWF ensemble member (0–49) this scenario sampled from")
    peak_depth_m: float = Field(..., ge=0)
    peak_time: datetime
    flood_extent_km2: float = Field(..., ge=0)
    total_volume_m3: float = Field(..., ge=0)


class EnsembleMember(BaseModel):
    """A single ECMWF ensemble member's flood prediction.

    Preserved individually for spaghetti plot rendering. Each member
    produces a different flood-front boundary — where they agree the
    forecast is confident, where they disagree it's uncertain.
    """

    member_id: int = Field(..., ge=0, le=49, description="ECMWF member index")
    flood_front: GeoJsonGeometry = Field(
        ...,
        description="GeoJSON LineString of predicted flood-front boundary at a given time. "
                    "When 50 of these are rendered semi-transparently, they form a natural "
                    "probability density — thick where they agree, wispy where they diverge."
    )
    peak_depth_m: float = Field(..., ge=0)
    peak_time: datetime
    flood_extent_km2: float = Field(..., ge=0)
    outcome_category: str = Field(
        ...,
        description="Classified outcome: 'catastrophic' (>3m), 'severe' (1-3m), "
                    "'moderate' (0.5-1m), 'minimal' (<0.5m)"
    )


class ProbabilisticFloodMap(BaseModel):
    """Spatial probability map — the core output of FloodPredictAgent.

    Each 30m grid cell has a probability [0–1] representing the fraction
    of 10,000 scenarios that flood that cell. This is rendered as the
    GeoJsonLayer with opacity = confidence, not just color = risk.
    """

    watershed_id: str
    bbox: BBox
    cell_probabilities: GeoJsonFeatureCollection = Field(
        ...,
        description="GeoJSON FeatureCollection where each Feature is a 30m cell "
                    "with properties: { probability: float, depth_median_m: float, "
                    "depth_p5_m: float, depth_p95_m: float }"
    )
    max_probability: float = Field(..., ge=0.0, le=1.0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class FloodTiming(BaseModel):
    """When the flood will peak — with uncertainty bounds.

    The confidence_interval_hours is what makes this honest:
    "Peak in 18h ± 6h" is more useful than "Peak in 18h".
    """

    peak_time: datetime
    confidence_interval_hours: float = Field(
        ..., ge=0,
        description="±hours around peak_time. Derived from ensemble spread."
    )
    earliest_peak: datetime = Field(..., description="5th percentile of peak time across members")
    latest_peak: datetime = Field(..., description="95th percentile of peak time across members")


class FloodDepthGrid(BaseModel):
    """Predicted flood depth per cell — the 3D extrusion source.

    This is what becomes the extruded ColumnLayer in deck.gl.
    Each cell has a median depth plus uncertainty bounds from the ensemble.
    """

    watershed_id: str
    bbox: BBox
    cells: GeoJsonFeatureCollection = Field(
        ...,
        description="Each Feature has properties: { depth_median_m, depth_p5_m, "
                    "depth_p25_m, depth_p75_m, depth_p95_m }. The p5–p95 range "
                    "is the probability fan for that cell."
    )
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ProbabilityFanPoint(BaseModel):
    """Probability fan data for a single map point over time.

    Requested when user clicks a point on the map. Shows how the
    predicted depth at that location evolves over time across the ensemble.
    """

    time_step: str = Field(..., description="Relative time, e.g. 'T+6h'")
    p5: float = Field(..., description="5th percentile depth (best case)")
    p25: float = Field(..., description="25th percentile depth")
    p50: float = Field(..., description="Median depth")
    p75: float = Field(..., description="75th percentile depth")
    p95: float = Field(..., description="95th percentile depth (worst case)")


class EnsembleDisagreement(BaseModel):
    """Breakdown of ensemble member outcomes for a zone.

    Displayed as disagreement badges on the map:
    "🔴 40% catastrophic / 🟠 35% severe / 🟡 20% moderate / 🟢 5% minimal"
    """

    zone_id: str
    catastrophic_pct: float = Field(..., ge=0, le=1, description="% of members predicting >3m depth")
    severe_pct: float = Field(..., ge=0, le=1, description="% predicting 1–3m")
    moderate_pct: float = Field(..., ge=0, le=1, description="% predicting 0.5–1m")
    minimal_pct: float = Field(..., ge=0, le=1, description="% predicting <0.5m")
    dominant_outcome: str = Field(..., description="Category with highest percentage")
    agreement_strength: float = Field(
        ..., ge=0, le=1,
        description="How strongly members agree. 1.0 = unanimous, 0.25 = completely split"
    )


class FloodForecast(BaseModel):
    """Complete flood forecast — composite output of FloodPredictAgent.

    This is what flows through the system to downstream agents.
    Contains both the collapsed probability map AND the full ensemble
    data for rich UI rendering.
    """

    forecast_id: str
    event_id: str
    watershed_id: str
    bbox: BBox

    # Collapsed outputs (for agent logic)
    probability_map: ProbabilisticFloodMap
    timing: FloodTiming
    depth_grid: FloodDepthGrid
    max_probability: float = Field(..., ge=0.0, le=1.0)

    # Ensemble detail (for UI — NOT collapsed)
    ensemble_members: list[EnsembleMember] = Field(
        default_factory=list,
        description="All 50 ensemble members preserved for spaghetti/fan/disagreement rendering"
    )
    representative_members: list[int] = Field(
        default_factory=list,
        description="Indices of 10 k-means-clustered representative members for cleaner spaghetti plot"
    )
    zone_disagreements: list[EnsembleDisagreement] = Field(
        default_factory=list,
        description="Per-zone disagreement breakdown for badge rendering"
    )

    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # LLM interpretation
    summary: Optional[str] = Field(
        None,
        description="LLM-generated forecast summary grounded in actual numbers"
    )
