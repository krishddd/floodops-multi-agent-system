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

from pydantic import BaseModel, Field

from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonGeometry


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


class ReturnPeriodEvent(BaseModel):
    """Exceedance of a return-period flood threshold across the ensemble.

    Paper-aligned (Nearing et al., Nature 627, 2024): flood skill is framed by
    return period (1/2/5/10-year events) rather than raw depth, because rarer
    events are both more impactful and harder to predict. ``exceedance_probability``
    is the fraction of ensemble members whose peak depth crosses this event's
    threshold — a deterministic consensus, computed without the LLM.
    """

    return_period_years: int = Field(..., description="Return period, e.g. 1, 2, 5, 10")
    threshold_depth_m: float = Field(..., ge=0, description="Peak depth (m) defining this event")
    exceedance_probability: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of ensemble members exceeding threshold_depth_m"
    )
    member_count: int = Field(..., ge=0, description="Members exceeding the threshold")


class LeadTimeSkill(BaseModel):
    """Estimated forecast reliability at a given lead time.

    Paper-aligned (Nearing et al., Nature 627, 2024): the AI model retains skill
    out to ~5-day lead time, matching the current state of the art's *nowcasts*.
    ``estimated_f1`` is a reference reliability (illustrative, distilled from the
    paper — not a live measurement), so the system can express how warning skill
    decays with how far ahead it is forecasting.
    """

    lead_time_days: int = Field(..., ge=0, description="Days ahead of the forecast issue time")
    estimated_f1: float = Field(
        ..., ge=0.0, le=1.0,
        description="Reference reliability (F1) at this lead time for the headline return period"
    )
    skill_retention: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of nowcast (0-day) skill retained at this lead time"
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
    return_period_events: list[ReturnPeriodEvent] = Field(
        default_factory=list,
        description="Per-return-period exceedance probabilities across the ensemble "
                    "(paper-aligned 1/2/5/10-yr framing). Deterministic — not LLM-gated."
    )
    max_return_period_years: int | None = Field(
        None,
        description="Largest return-period event the ensemble agrees on "
                    "(>= RETURN_PERIOD_MEMBER_AGREEMENT of members). None if below 1-yr."
    )
    lead_time_skill: list[LeadTimeSkill] = Field(
        default_factory=list,
        description="Reference reliability decay across the 7-day forecast horizon "
                    "(paper-aligned). Deterministic — not LLM-gated."
    )
    skillful_lead_days: int | None = Field(
        None,
        description="Effective warning horizon: largest lead time whose estimated "
                    "F1 stays >= SKILLFUL_F1_THRESHOLD for the headline return period."
    )

    # GloFAS benchmark reference (paper-faithful: streamflow is NEVER a model
    # input — these fields compare our forecast against the state-of-the-art
    # benchmark the way Nearing et al. 2024 do, using real basin-specific
    # return-period thresholds fit from the 1984→present GloFAS reanalysis).
    benchmark_discharge_thresholds_m3s: dict[int, float] | None = Field(
        None,
        description="Per-basin return-period discharge thresholds (m³/s) fit from "
                    "the historical GloFAS reanalysis via Weibull plotting positions "
                    "(Bulletin 17B framing). Keys are return periods in years."
    )
    benchmark_peak_discharge_m3s: float | None = Field(
        None,
        description="Peak of the GloFAS forecast-discharge ensemble mean over the "
                    "forecast horizon (m³/s). Benchmark reference only."
    )
    benchmark_return_period_years: int | None = Field(
        None,
        description="Return period the GloFAS benchmark forecast itself reaches "
                    "against the basin's fitted thresholds. None = sub-1-yr."
    )

    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # LLM interpretation
    summary: str | None = Field(
        None,
        description="LLM-generated forecast summary grounded in actual numbers"
    )
