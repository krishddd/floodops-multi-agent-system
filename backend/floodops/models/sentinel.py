"""
SentinelAgent data models.

SentinelAgent is the base data layer — it polls raw sensor APIs (NOAA,
USGS, ESA) and emits AnomalyAlerts when z-scores exceed configured thresholds.
Every downstream agent subscribes to these alerts; they never touch raw APIs.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from floodops.models.enums import AlertLevel, DataSource
from floodops.models.geo import BBox, Coordinate


class SensorReading(BaseModel):
    """A single measurement from any sensor source.

    This is the raw input — before anomaly detection.
    SentinelAgent normalizes readings from heterogeneous sources
    (NOAA radar, USGS gauges, ESA soil moisture) into this
    common format before comparing against baselines.
    """

    sensor_id: str = Field(..., description="Unique sensor identifier, e.g. 'USGS-01646500'")
    source: DataSource = Field(..., description="Which external data source")
    metric: str = Field(..., description="What's being measured: 'rainfall_mm', 'water_level_m', 'soil_saturation_pct'")
    value: float = Field(..., description="Raw measurement value")
    unit: str = Field(..., description="Measurement unit, e.g. 'mm', 'm', '%'")
    location: Coordinate
    watershed_id: str = Field(..., description="HydroBASINS watershed ID this sensor belongs to")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    quality_flag: str | None = Field(None, description="Data quality indicator from source")


class Baseline(BaseModel):
    """Rolling statistical baseline per watershed per metric.

    SentinelAgent maintains 30, 90, and 365-day baselines.
    Z-score = (current - mean) / std. Anomaly if |z| > threshold.
    """

    watershed_id: str
    metric: str
    window_days: int = Field(..., description="Baseline window: 30, 90, or 365 days")
    mean: float
    std: float = Field(..., gt=0, description="Standard deviation — must be positive")
    sample_count: int = Field(..., ge=1, description="Number of readings in baseline")
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class AnomalyAlert(BaseModel):
    """Emitted by SentinelAgent when sensor readings deviate from baseline.

    This is the primary trigger for the entire system. When an AnomalyAlert
    is emitted to the 'anomaly_alerts' queue, FloodPredictAgent wakes up
    and runs its ensemble model.

    Multi-sensor confidence: alert is only raised when 2+ independent sensors
    agree on anomaly direction, reducing false positives.
    """

    alert_id: str = Field(..., description="Unique alert identifier (UUID)")
    level: AlertLevel = Field(..., description="Severity based on z-score magnitude")
    metric: str = Field(..., description="Which metric triggered: rainfall, water_level, etc.")
    value: float = Field(..., description="Current reading that triggered the alert")
    deviation_sigma: float = Field(..., description="Absolute z-score value")
    location: Coordinate
    watershed_id: str
    bbox: BBox = Field(..., description="Affected area bounding box")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Multi-sensor agreement confidence")
    agreeing_sensors: int = Field(..., ge=1, description="Number of sensors confirming this anomaly")
    total_sensors: int = Field(..., ge=1, description="Total sensors in watershed for this metric")
    source_readings: list[SensorReading] = Field(default_factory=list, description="The raw readings that contributed")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    description: str | None = Field(None, description="LLM-generated interpretation of this anomaly")


class FloodRecedingEvent(BaseModel):
    """Emitted by SentinelAgent when flood waters begin receding.

    Triggers DiseaseRiskAgent to begin pathogen risk modeling.
    Identified when river gauge levels drop for 4+ consecutive hours.
    """

    event_id: str
    zone_id: str
    bbox: BBox
    peak_water_level_m: float
    peak_timestamp: datetime
    recession_start: datetime
    flood_duration_hours: float = Field(..., description="How long the area was inundated")
    flood_depth_max_m: float
    timestamp: datetime = Field(default_factory=datetime.utcnow)
