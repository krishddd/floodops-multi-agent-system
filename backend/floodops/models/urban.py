"""
UrbanRiskAgent data models.

UrbanRiskAgent intersects flood predictions with city infrastructure:
buildings, roads, drainage networks, population density. It answers
"which STREET is impassable" and "which BUILDING has 200 people on
the ground floor" — questions a watershed flood model can't answer.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonGeometry


class ZoneRiskReport(BaseModel):
    """Risk assessment for a single urban zone.

    Each zone is a neighborhood/ward-level polygon. The risk report
    combines flood probability with urban vulnerability factors.
    """

    zone_id: str
    zone_name: str
    population: int = Field(..., ge=0)
    risk_level: str = Field(..., description="LOW / MEDIUM / HIGH / CRITICAL")
    risk_score: float = Field(..., ge=0.0, le=1.0)
    flood_probability: float = Field(..., ge=0.0, le=1.0)
    predicted_depth_m: float = Field(..., ge=0)
    drainage_gap_mm: float = Field(
        0.0,
        description="Design rainfall standard minus current observed extreme. "
                    "Positive = infrastructure undersized for current climate."
    )
    buildings_at_risk: int = Field(0, ge=0)
    key_assets: list[str] = Field(default_factory=list, description="Hospitals, schools, power stations in zone")
    impervious_fraction: float = Field(0.0, ge=0.0, le=1.0, description="Fraction of concrete/asphalt")

    # LLM reasoning for spatial "why" card
    reasoning: str | None = Field(None, description="LLM-generated explanation of this zone's risk")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence in this assessment — maps to visual opacity")
    competing_hypothesis: str | None = Field(None, description="What minority ensemble members predict for this zone")


class RouteSet(BaseModel):
    """Evacuation routes for a zone — shown as ArcLayer in deck.gl."""

    zone_id: str
    safe_roads: GeoJsonFeatureCollection = Field(..., description="Passable road segments as GeoJSON")
    blocked_roads: GeoJsonFeatureCollection = Field(default_factory=GeoJsonFeatureCollection, description="Impassable segments")
    shelters: list[ShelterInfo] = Field(default_factory=list)
    estimated_evacuation_time_minutes: float = Field(0, ge=0)
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class ShelterInfo(BaseModel):
    """Emergency shelter information for evacuation routing."""

    shelter_id: str
    name: str
    lat: float
    lng: float
    capacity: int = Field(..., ge=0)
    current_occupancy: int = Field(0, ge=0)
    distance_km: float = Field(0, ge=0, description="Distance from zone centroid")
    is_accessible: bool = True


class DamagePolygon(BaseModel):
    """Post-flood damage area from pre/post satellite comparison."""

    polygon_id: str
    geometry: GeoJsonGeometry
    damage_type: str = Field(..., description="structural, agricultural, infrastructure")
    area_km2: float = Field(..., ge=0)
    building_count: int = Field(0, ge=0)
    estimated_cost_usd: float | None = None


class UrbanRiskReport(BaseModel):
    """Complete output from UrbanRiskAgent.

    Contains per-zone risk, evacuation routes, and (post-flood) damage assessment.
    """

    report_id: str
    event_id: str
    city_id: str
    bbox: BBox
    zones: list[ZoneRiskReport] = Field(default_factory=list)
    routes: list[RouteSet] = Field(default_factory=list)
    drainage_gaps: GeoJsonFeatureCollection = Field(
        default_factory=GeoJsonFeatureCollection,
        description="Infrastructure operating beyond design capacity"
    )
    damage_polygons: list[DamagePolygon] = Field(default_factory=list)
    total_population_at_risk: int = Field(0, ge=0)
    mapping_complete: bool = Field(False, description="Gate condition — orchestrator checks this before allowing evacuation")
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# Fix forward reference — RouteSet references ShelterInfo which is defined above
RouteSet.model_rebuild()
