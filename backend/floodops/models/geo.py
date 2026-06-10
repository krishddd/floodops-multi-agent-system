"""
Geospatial primitives used across all FloodOps models.

Every agent that deals with spatial data (which is all of them)
uses these base types for coordinates, bounding boxes, and GeoJSON.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Coordinate(BaseModel):
    """A geographic point (WGS84)."""

    lat: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    lng: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")


class BBox(BaseModel):
    """Axis-aligned bounding box (WGS84).

    Used by every connector to define the area of interest for data queries.
    Order: south, west, north, east (matching STAC/OGC conventions).
    """

    south: float = Field(..., ge=-90, le=90)
    west: float = Field(..., ge=-180, le=180)
    north: float = Field(..., ge=-90, le=90)
    east: float = Field(..., ge=-180, le=180)

    @field_validator("north")
    @classmethod
    def north_ge_south(cls, v: float, info) -> float:
        if "south" in info.data and v < info.data["south"]:
            raise ValueError("north must be >= south")
        return v

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.south, self.west, self.north, self.east)

    def center(self) -> Coordinate:
        return Coordinate(
            lat=(self.south + self.north) / 2,
            lng=(self.west + self.east) / 2,
        )


class GeoJsonGeometry(BaseModel):
    """GeoJSON geometry object (RFC 7946)."""

    type: Literal[
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    ]
    coordinates: Any = Field(..., description="Coordinate array per geometry type")


class GeoJsonFeature(BaseModel):
    """GeoJSON Feature with typed properties."""

    type: Literal["Feature"] = "Feature"
    geometry: GeoJsonGeometry
    properties: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class GeoJsonFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection — the standard interchange format for map layers."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJsonFeature] = Field(default_factory=list)

    def __len__(self) -> int:
        return len(self.features)


class DataCadenceBadge(BaseModel):
    """Honest data-freshness badge for a source.

    Displayed in the UI layer panel and on spatial "why" cards
    so decision-makers know what's fresh and what's stale.
    """

    source: str = Field(..., description="DataSource enum value")
    expected_cadence: str = Field(..., description="Human-readable cadence, e.g. '15 min'")
    last_updated_iso: str | None = Field(None, description="ISO timestamp of last data")
    freshness: Literal["fresh", "within_cadence", "stale", "static", "on_demand"] = "static"
    emoji: str = Field("⚪", description="Visual indicator: 🟢 🟡 🔴 ⚪ 🔵")
