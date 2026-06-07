"""
What-if scenario models.

Enables interactive exploration: user adjusts rainfall intensity,
dam-break timing, or soil saturation via UI sliders, and the system
re-runs FloodPredictAgent with modified parameters to show the diff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from floodops.models.geo import GeoJsonFeatureCollection


class ScenarioParams(BaseModel):
    """User-adjustable parameters for what-if scenarios.

    Each field maps to a slider in the scenario panel UI.
    None = use current real value (no override).
    """

    rainfall_mm_24h: Optional[float] = Field(None, ge=0, description="Override 24h rainfall total")
    rainfall_shift_km: Optional[float] = Field(None, description="Shift rainfall center east(+)/west(-)")
    soil_saturation_pct: Optional[float] = Field(None, ge=0, le=100, description="Override soil saturation %")
    dam_break_time_h: Optional[float] = Field(None, ge=0, description="Hours from now until GLOF breach")
    dam_break_lake_id: Optional[str] = Field(None, description="Which lake to breach in scenario")
    ensemble_member_filter: Optional[list[int]] = Field(None, description="Only use these ensemble members")

    # Presets
    preset: Optional[str] = Field(
        None,
        description="Named preset: 'worst_case', 'best_case', 'glof_breach', 'climate_plus_2c'"
    )


class ScenarioDiff(BaseModel):
    """Difference between current forecast and scenario.

    These deltas are shown in the scenario panel and rendered
    as dashed outlines (red=worse, green=better) on the map.
    """

    delta_population_at_risk: int = Field(0, description="Positive = more people at risk")
    delta_peak_depth_m: float = Field(0, description="Positive = deeper flooding")
    delta_peak_time_hours: float = Field(0, description="Negative = earlier peak (worse)")
    delta_flood_extent_km2: float = Field(0, description="Positive = larger flood area")
    delta_max_probability: float = Field(0, description="Change in max flood probability")
    summary: str = Field("", description="LLM-generated comparison summary")


class ScenarioResult(BaseModel):
    """Complete result of a what-if scenario run."""

    scenario_id: str
    params: ScenarioParams
    current_forecast: GeoJsonFeatureCollection = Field(..., description="Current prediction GeoJSON")
    scenario_forecast: GeoJsonFeatureCollection = Field(..., description="Modified prediction GeoJSON")
    diff: ScenarioDiff
    diff_overlay: GeoJsonFeatureCollection = Field(
        ...,
        description="GeoJSON showing ONLY the differences: red=worse, green=better. "
                    "Used by diff-renderer.js for overlay mode."
    )
    computation_time_ms: int = Field(0, ge=0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ScenarioPreset(BaseModel):
    """Named scenario preset for quick exploration."""

    name: str
    label: str = Field(..., description="Human-readable label for UI button")
    description: str
    params: ScenarioParams
    icon: str = Field("⚡", description="Emoji icon for UI")
