"""
AlertAgent data models.

AlertAgent handles multi-channel, multi-language warning dissemination.
The hardest part of flood warning is not prediction — it's getting a
message to a farmer in rural Bangladesh at 2 AM, in Bangla, telling
them specifically which road is still passable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from floodops.models.enums import SeverityLevel
from floodops.models.geo import GeoJsonGeometry


class CellBroadcast(BaseModel):
    """Mass SMS broadcast to all phones in a geographic polygon.

    Uses cell broadcast (no phone number list needed — broadcasts to
    every phone connected to cell towers in the zone polygon).
    """

    broadcast_id: str
    severity: SeverityLevel
    zone_polygon: GeoJsonGeometry
    message_text: str = Field(..., max_length=1600, description="Broadcast message content")
    language: str = Field("en", description="ISO 639-1 language code")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    reach_estimate: int = Field(0, ge=0, description="Estimated phones in coverage area")
    evacuation_route_url: Optional[str] = Field(None, description="Link to live evacuation map")


class RadioBroadcast(BaseModel):
    """Localized radio broadcast script for community radio stations."""

    broadcast_id: str
    severity: SeverityLevel
    station_ids: list[str] = Field(default_factory=list)
    script_text: str
    language: str = Field("en")
    priority_level: int = Field(1, ge=1, le=5, description="1=highest priority")
    duration_seconds: int = Field(60, ge=10)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SirenActivation(BaseModel):
    """Municipal siren activation command."""

    activation_id: str
    zone_ids: list[str] = Field(..., min_length=1)
    pattern: str = Field("FLOOD_WARNING", description="FLOOD_WARNING or FLOOD_EMERGENCY")
    duration_seconds: int = Field(120, ge=30)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AlertDispatch(BaseModel):
    """Complete alert dispatch record — all channels for one event."""

    dispatch_id: str
    event_id: str
    severity: SeverityLevel
    cell_broadcasts: list[CellBroadcast] = Field(default_factory=list)
    radio_broadcasts: list[RadioBroadcast] = Field(default_factory=list)
    siren_activations: list[SirenActivation] = Field(default_factory=list)
    email_sent: bool = False
    total_reach_estimate: int = Field(0, ge=0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_glof_bypass: bool = Field(False, description="True if triggered by GLOF direct HTTP bypass")
