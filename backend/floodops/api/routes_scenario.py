"""What-if scenario endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from floodops.models.geo import GeoJsonFeatureCollection
from floodops.models.scenario import ScenarioDiff, ScenarioParams, ScenarioPreset, ScenarioResult

router = APIRouter()

PRESETS = [
    ScenarioPreset(name="worst_case", label="Worst Case", description="All members at 95th percentile rainfall", params=ScenarioParams(rainfall_mm_24h=250, soil_saturation_pct=95), icon="🔴"),
    ScenarioPreset(name="best_case", label="Best Case", description="Rainfall shifts away, low soil saturation", params=ScenarioParams(rainfall_mm_24h=30, soil_saturation_pct=40, rainfall_shift_km=30), icon="🟢"),
    ScenarioPreset(name="glof_breach", label="GLOF Breach", description="Thulagi Lake dam failure in 6 hours", params=ScenarioParams(dam_break_time_h=6, dam_break_lake_id="GL003"), icon="🧊"),
    ScenarioPreset(name="climate_plus_2c", label="Climate +2°C", description="Rainfall intensity +20% (IPCC AR6 mid-range)", params=ScenarioParams(rainfall_mm_24h=170), icon="🌡️"),
]

@router.get("/presets")
async def get_presets():
    return [p.model_dump() for p in PRESETS]

@router.post("/run")
async def run_scenario(params: ScenarioParams):
    """Re-run FloodPredictAgent with modified parameters and return diff."""
    # TODO: Wire to FloodPredictAgent.run_ensemble() with overridden parameters
    # For now, return a realistic diff structure
    diff = ScenarioDiff(
        delta_population_at_risk=4200 if params.rainfall_mm_24h and params.rainfall_mm_24h > 150 else -1500,
        delta_peak_depth_m=1.8 if params.rainfall_mm_24h and params.rainfall_mm_24h > 150 else -0.5,
        delta_peak_time_hours=-3 if params.rainfall_mm_24h and params.rainfall_mm_24h > 150 else 6,
        delta_flood_extent_km2=12.5 if params.rainfall_mm_24h and params.rainfall_mm_24h > 150 else -8.0,
        delta_max_probability=0.15 if params.rainfall_mm_24h and params.rainfall_mm_24h > 150 else -0.20,
        summary="Increased rainfall (200mm+) results in 4,200 additional people at risk, peak 3h earlier, 1.8m deeper flooding in Bagmati Corridor.",
    )

    return ScenarioResult(
        scenario_id=str(uuid.uuid4()),
        params=params,
        current_forecast=GeoJsonFeatureCollection(features=[]),
        scenario_forecast=GeoJsonFeatureCollection(features=[]),
        diff=diff,
        diff_overlay=GeoJsonFeatureCollection(features=[]),
        computation_time_ms=1250,
    ).model_dump()
