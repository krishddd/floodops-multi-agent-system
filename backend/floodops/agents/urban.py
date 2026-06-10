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
from typing import Any

from floodops.agents.base import BaseAgent, _as_dict
from floodops.llm.prompts import URBAN_AGENT_SYSTEM_PROMPT
from floodops.models.enums import TriggerType
from floodops.models.geo import BBox, GeoJsonFeatureCollection
from floodops.models.reasoning import ReasonedAssessment
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
        await self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        self.log_action("initialize", "UrbanRiskAgent subscribed to flood_forecasts", 1.0)

    async def handle_event(self, channel: str, payload: Any) -> None:
        pass

    async def handle_forecast(self, channel: str, forecast_data: Any) -> None:
        """Process incoming flood forecast and generate urban risk report."""
        forecast_data = _as_dict(forecast_data)
        report = await self.map_urban_risk(forecast_data)
        if report:
            await self.event_bus.emit("urban_risk", report.model_dump())
            self.log_action(
                "emit_urban_risk",
                f"Mapped {len(report.zones)} zones, {report.total_population_at_risk} "
                f"people at risk. Multi-scale rollup — {self._multiscale_summary(report.zones)}",
                0.8,
            )

    @staticmethod
    def _multiscale_summary(zones) -> str:
        """Watershed → district → street rollup: max risk per district."""
        districts: dict[str, float] = {}
        for z in zones:
            # District inferred from zone name (Kathmandu valley municipalities).
            name = getattr(z, "zone_name", "") or ""
            district = next((d for d in ("Kirtipur", "Lalitpur", "Bagmati", "Patan",
                                          "Bhaktapur", "Thimi") if d in name), "Other")
            districts[district] = max(districts.get(district, 0.0), getattr(z, "risk_score", 0.0))
        ranked = sorted(districts.items(), key=lambda t: t[1], reverse=True)
        return "; ".join(f"{d} {r:.0%}" for d, r in ranked[:4])

    async def map_urban_risk(self, forecast_data: dict[str, Any]) -> UrbanRiskReport | None:
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

        # Real OSM building footprints (keyless Overpass) when a connector is
        # wired — biases per-zone buildings_at_risk; falls back to mock otherwise.
        osm_buildings = await self._fetch_osm_buildings(bbox)

        # Generate mock zone reports, then LLM-enrich the high-risk ones.
        zones = self._generate_mock_zones(bbox, max_prob, osm_buildings=osm_buildings)
        zones = [await self._enrich_zone(z) for z in zones]
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

    async def _enrich_zone(self, zone: ZoneRiskReport) -> ZoneRiskReport:
        """Reflexion-refine reasoning + confidence for HIGH/CRITICAL zones.

        No-ops (returns the zone unchanged) when no LLM is configured or the
        zone is not high-risk — preserving the deterministic mock output.
        """
        if zone.risk_level not in ("HIGH", "CRITICAL") or not self._llm_ready():
            return zone

        mock = ReasonedAssessment(
            agent_id=self.agent_id,
            value=zone.risk_score,
            confidence=max(0.1, zone.confidence),
            summary=zone.reasoning,
            causal_factors=["drainage capacity gap", "impervious surface",
                            "population density"],
            competing_hypothesis=zone.competing_hypothesis,
        )
        assessment = await self._run_with_reflexion(
            system=URBAN_AGENT_SYSTEM_PROMPT,
            data={
                "zone_name": zone.zone_name,
                "flood_probability": zone.flood_probability,
                "predicted_depth_m": zone.predicted_depth_m,
                "population": zone.population,
                "drainage_gap_mm": zone.drainage_gap_mm,
                "key_assets": zone.key_assets,
                "buildings_at_risk": zone.buildings_at_risk,
            },
            context={"risk_level": zone.risk_level},
            schema=ReasonedAssessment,
            mock=mock,
        )
        return zone.model_copy(update={
            "reasoning": assessment.summary,
            "confidence": assessment.confidence,
            "competing_hypothesis": assessment.competing_hypothesis
            or zone.competing_hypothesis,
        })

    async def _fetch_osm_buildings(self, bbox: BBox) -> int | None:
        """Total OSM building count for the bbox (real); None on failure/no connector."""
        if self.connector is None:
            return None
        try:
            data = await self.connector.fetch_latest(bbox=bbox)
            count = int((data or {}).get("buildings_count") or 0)
            return count or None
        except Exception as exc:
            self._logger.warning("OSM fetch failed: %s", exc)
            return None

    def _generate_mock_zones(
        self, bbox: BBox, max_prob: float, osm_buildings: int | None = None
    ) -> list[ZoneRiskReport]:
        """Generate realistic zone risk reports for demo.

        When ``osm_buildings`` (real OSM count) is provided, per-zone
        buildings_at_risk are derived from it rather than a random guess.
        """
        import random
        random.seed(123)

        zone_names = [
            ("zone_1", "Kirtipur Ward 5"), ("zone_2", "Lalitpur Central"),
            ("zone_3", "Bagmati Corridor"), ("zone_4", "Patan Industrial"),
            ("zone_5", "Bhaktapur Old Town"), ("zone_6", "Thimi Agricultural"),
        ]

        # Even share of real OSM buildings across zones (when available).
        per_zone_buildings = (osm_buildings // len(zone_names)) if osm_buildings else None

        zones = []
        for zone_id, zone_name in zone_names:
            prob = min(1.0, max_prob * random.uniform(0.3, 1.2))
            depth = round(prob * random.uniform(0.5, 4.0), 1)
            pop = random.randint(2000, 25000)
            # Real building exposure scaled by flood probability, else mock.
            buildings = (int(per_zone_buildings * prob) if per_zone_buildings
                         else random.randint(50, 500))

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
                buildings_at_risk=buildings,
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
