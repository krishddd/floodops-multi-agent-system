"""
ResourceAgent data models.

ResourceAgent handles logistics: pre-positioning supplies BEFORE the flood,
routing rescue teams DURING the flood (using flood extent as navigable water),
and distributing medical supplies AFTER the flood to disease hotspots.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from floodops.models.geo import Coordinate, GeoJsonGeometry


class SupplyItem(BaseModel):
    """A single supply type with quantity."""

    item_type: str = Field(..., description="ORS_sachets, antibiotic_courses, water_purification_tabs, rescue_boats")
    quantity: int = Field(..., ge=0)
    unit: str = Field("units")


class StagingLocation(BaseModel):
    """Pre-positioning staging area outside the flood zone."""

    staging_id: str
    name: str
    location: Coordinate
    capacity_tons: float = Field(..., ge=0)
    is_outside_flood_zone: bool = True
    travel_hours_to_zone: float = Field(..., ge=0)
    road_accessible: bool = True


class LogisticsOrder(BaseModel):
    """A single supply movement order."""

    order_id: str
    vehicle_id: Optional[str] = None
    route: GeoJsonGeometry = Field(..., description="GeoJSON LineString of vehicle route")
    payload: list[SupplyItem] = Field(default_factory=list)
    origin: Coordinate
    destination: StagingLocation
    deadline: datetime
    status: str = Field("pending", description="pending / in_transit / delivered")


class RescueRoute(BaseModel):
    """Rescue team routing during active flood.

    During active flooding, flood extent becomes navigable water for boats.
    Routes are optimized to maximize population reached per travel hour.
    """

    route_id: str
    team_id: str
    route_via_water: GeoJsonGeometry = Field(..., description="GeoJSON LineString — may traverse flooded areas")
    target_population: int = Field(..., ge=0)
    priority_score: float = Field(..., ge=0.0, le=1.0)
    estimated_reach_time_minutes: float = Field(..., ge=0)


class DistributionPlan(BaseModel):
    """Post-flood medical supply distribution to disease hotspots."""

    plan_id: str
    zone_id: str
    supply_types: list[SupplyItem] = Field(default_factory=list)
    delivery_window_hours: float = Field(
        ..., ge=0,
        description="Must arrive before symptom onset. Cholera: 48h. Typhoid: 144h."
    )
    route: Optional[GeoJsonGeometry] = None
    priority: int = Field(1, ge=1, description="1=highest priority")


class ResourceOrders(BaseModel):
    """Complete ResourceAgent output for an event."""

    event_id: str
    logistics_orders: list[LogisticsOrder] = Field(default_factory=list)
    rescue_routes: list[RescueRoute] = Field(default_factory=list)
    distribution_plans: list[DistributionPlan] = Field(default_factory=list)
    supplies_prepositioned: bool = Field(False, description="Gate condition for orchestrator")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
