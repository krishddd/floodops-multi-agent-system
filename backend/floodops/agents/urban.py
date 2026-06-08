"""
UrbanRiskAgent — City vulnerability mapping and evacuation routing.

Intersects flood predictions with city infrastructure (buildings, roads,
drainage, population). Answers the questions a watershed model can't:
"which street is impassable?", "which building has 200 people on the
ground floor?", "which road leads to a shelter?"

Trigger: Queue from FloodPredictAgent flood_forecasts.
Emits: UrbanRiskReport → urban_risk queue
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from floodops.agents.base import BaseAgent
from floodops.models.enums import TriggerType
from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonGeometry
from floodops.models.urban import (
    RouteSet,
    ShelterInfo,
    UrbanRiskReport,
    ZoneRiskReport,
)


class UrbanRiskAgent(BaseAgent):
    """City vulnerability mapping and evacuation intelligence.

    Generates per-zone risk reports with LLM-authored reasoning for
    spatial "why" cards, plus evacuation routes rendered as ArcLayer arcs.
    """

    agent_id: str = "urban_risk_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE]

    async def initialize(self) -> None:
        self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        await self.log_action("initialize", "UrbanRiskAgent subscribed to flood_forecasts", 1.0)

    async def handle_forecast(self, forecast_data: dict[str, Any]) -> None:
        """Process incoming flood forecast and generate urban risk report."""
        report = await self.map_urban_risk(forecast_data)
        if report:
            await self.event_bus.emit("urban_risk", report.model_dump())
            await self.log_action(
                "emit_urban_risk",
                f"Mapped {len(report.zones)} zones, {report.total_population_at_risk} people at risk",
                0.8,
            )

    async def map_urban_risk(self, forecast_data: dict[str, Any]) -> Optional[UrbanRiskReport]:
        """Intersect flood forecast with urban layers.

        Steps:
        1. Fetch OSM buildings, roads, drainage for the forecast bbox
        2. Fetch WorldPop population density grid
        3. Intersect flood probability map with building/road layers
        4. Calculate per-zone vulnerability index
        5. A* pathfind evacuation routes (blocking flooded roads)
        6. Generate LLM reasoning for each zone's "why" card

        TODO: Implement real OSM/WorldPop queries and pathfinding.
        Currently generates mock zone reports with realistic structure.
        """
        bbox_data = forecast_data.get("bbox", {})
        bbox = BBox(**bbox_data) if bbox_data else BBox(south=27.2, west=84.8, north=28.2, east=85.8)
        max_prob = forecast_data.get("max_probability", 0.5)
        event_id = forecast_data.get("event_id", str(uuid.uuid4()))

        # Generate mock zone reports
        zones = self._generate_mock_zones(bbox, max_prob)
        routes = self._generate_mock_routes(zones)
        total_pop = sum(z.population for z in zones if z.risk_level in ("HIGH", "CRITICAL"))

        report = UrbanRiskReport(
            report_id=str(uuid.uuid4()),
            event_id=event_id,
            city_id="kathmandu",
            bbox=bbox,
            zones=zones,
            routes=routes,
            total_population_at_risk=total_pop,
            mapping_complete=True,  # Gate condition for orchestrator
        )
        return report

    def _generate_mock_zones(self, bbox: BBox, max_prob: float) -> list[ZoneRiskReport]:
        """Generate realistic zone risk reports for demo."""
        import random
        random.seed(123)

        zone_names = [
            ("zone_1", "Kirtipur Ward 5"), ("zone_2", "Lalitpur Central"),
            ("zone_3", "Bagmati Corridor"), ("zone_4", "Patan Industrial"),
            ("zone_5", "Bhaktapur Old Town"), ("zone_6", "Thimi Agricultural"),
        ]

        zones = []
        for zone_id, zone_name in zone_names:
            prob = min(1.0, max_prob * random.uniform(0.3, 1.2))
            depth = round(prob * random.uniform(0.5, 4.0), 1)
            pop = random.randint(2000, 25000)

            if prob > 0.8:
                risk = "CRITICAL"
            elif prob > 0.6:
                risk = "HIGH"
            elif prob > 0.3:
                risk = "MEDIUM"
            else:
                risk = "LOW"

            zones.append(ZoneRiskReport(
                zone_id=zone_id,
                zone_name=zone_name,
                population=pop,
                risk_level=risk,
                risk_score=round(prob, 2),
                flood_probability=round(prob, 2),
                predicted_depth_m=depth,
                drainage_gap_mm=round(random.uniform(0, 80), 1),
                buildings_at_risk=random.randint(50, 500),
                key_assets=random.sample(
                    ["Hospital", "School", "Power Station", "Water Treatment", "Bridge"],
                    k=random.randint(1, 3),
                ),
                impervious_fraction=round(random.uniform(0.4, 0.9), 2),
                reasoning=(
                    f"Zone {zone_name} shows {prob:.0%} flood probability with {depth}m predicted depth. "
                    f"Upstream gauge reads 3.2σ above baseline. {pop:,} residents in zone, "
                    f"drainage capacity gap of {round(random.uniform(0, 80), 1)}mm — infrastructure "
                    f"was designed for a 1-in-100-year event but current rainfall is 1-in-250-year equivalent."
                ),
                confidence=round(random.uniform(0.5, 0.95), 2),
                competing_hypothesis=(
                    f"12 of 50 ensemble members predict rainfall shifting 20km east, "
                    f"reducing this zone to minor flooding (0.3m). "
                    f"If this occurs, {zone_name} would drop to LOW risk."
                ) if random.random() > 0.4 else None,
            ))

        return zones

    def _generate_mock_routes(self, zones: list[ZoneRiskReport]) -> list[RouteSet]:
        """Generate mock evacuation routes."""
        routes = []
        for zone in zones:
            if zone.risk_level in ("HIGH", "CRITICAL"):
                routes.append(RouteSet(
                    zone_id=zone.zone_id,
                    safe_roads=GeoJsonFeatureCollection(features=[]),
                    shelters=[
                        ShelterInfo(
                            shelter_id=f"shelter_{zone.zone_id}",
                            name=f"{zone.zone_name} High School",
                            lat=27.7 + 0.01,
                            lng=85.3 + 0.01,
                            capacity=500,
                            current_occupancy=0,
                            distance_km=1.2,
                        ),
                    ],
                    estimated_evacuation_time_minutes=25.0,
                ))
        return routes
