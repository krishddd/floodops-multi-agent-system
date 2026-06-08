"""
DiseaseRiskAgent — Post-flood disease outbreak prediction.

Every major flood is followed by a disease outbreak. Cholera: 2-5 day
incubation, Typhoid: 6-30 days, Leptospirosis: 2-30 days. The intervention
window is the incubation period — if supplies arrive before symptoms,
the outbreak is preventable.

Trigger: Queue from SentinelAgent (flood_receding event).
Emits: DiseaseRiskReport → disease_risk queue
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from floodops.agents.base import BaseAgent
from floodops.models.enums import Pathogen, TriggerType
from floodops.models.geo import BBox, GeoJsonFeatureCollection
from floodops.models.disease import (
    DiseaseRiskMap,
    DiseaseRiskReport,
    Hotspot,
    MedicalSupplyOrder,
)


class DiseaseRiskAgent(BaseAgent):
    """Post-flood pathogen prediction — operates in the incubation window."""

    agent_id: str = "disease_risk_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE]

    async def initialize(self) -> None:
        await self.event_bus.subscribe("flood_receding", self.handle_flood_receding)
        self.log_action("initialize", "DiseaseRiskAgent subscribed to flood_receding", 1.0)

    async def handle_event(self, channel: str, payload: Any) -> None:
        pass

    async def handle_flood_receding(self, event_data: dict[str, Any]) -> None:
        """Model disease risk once flood waters begin receding."""
        report = await self.forecast_disease_risk(event_data)
        if report:
            await self.event_bus.emit("disease_risk", report.model_dump())
            self.log_action(
                "emit_disease_risk",
                f"Identified {len(report.hotspots)} hotspots, "
                f"generated {len(report.supply_orders)} supply orders",
                0.75,
            )

    async def forecast_disease_risk(self, event_data: dict[str, Any]) -> Optional[DiseaseRiskReport]:
        """Predict cholera, typhoid, and leptospirosis risk.

        Risk models (to be replaced with real epidemiological models):
        - Cholera: P ∝ flood_depth × duration × (1 - sanitation) × population
        - Typhoid: P ∝ P(water_contaminated) × population_without_piped_water
        - Lepto:   P ∝ flood_extent × rodent_habitat × outdoor_workers

        TODO: Wire real WHO EWARN data and JMP WASH infrastructure.
        """
        import random
        random.seed(456)

        event_id = event_data.get("event_id", str(uuid.uuid4()))
        bbox_data = event_data.get("bbox", {})
        bbox = BBox(**bbox_data) if bbox_data else BBox(south=27.2, west=84.8, north=28.2, east=85.8)
        flood_depth = event_data.get("flood_depth_max_m", 2.0)
        flood_duration = event_data.get("flood_duration_hours", 36.0)

        # Generate risk maps for three time windows
        risk_maps = []
        for window in ["0-7d", "7-14d", "14-30d"]:
            risk_maps.append(DiseaseRiskMap(
                map_id=str(uuid.uuid4()),
                event_id=event_id,
                bbox=bbox,
                cells=GeoJsonFeatureCollection(features=[]),
                time_window=window,
            ))

        # Identify hotspots (risk > 0.7)
        hotspots = []
        supply_orders = []
        center = bbox.center()

        for pathogen, base_risk in [(Pathogen.CHOLERA, 0.6), (Pathogen.TYPHOID, 0.4), (Pathogen.LEPTOSPIROSIS, 0.3)]:
            risk = min(1.0, base_risk * (flood_depth / 2.0) * (flood_duration / 24.0) * random.uniform(0.8, 1.2))

            if risk > 0.7:
                peak_days = {"cholera": 3, "typhoid": 10, "leptospirosis": 7}[pathogen.value]
                pop_exposed = random.randint(5000, 20000)

                hotspots.append(Hotspot(
                    zone_id=f"zone_{pathogen.value}",
                    pathogen=pathogen,
                    risk_score=round(risk, 2),
                    peak_date=datetime.utcnow() + timedelta(days=peak_days),
                    population_exposed=pop_exposed,
                    lat=center.lat + random.uniform(-0.1, 0.1),
                    lng=center.lng + random.uniform(-0.1, 0.1),
                ))

                intervention_hours = {"cholera": 48, "typhoid": 144, "leptospirosis": 72}[pathogen.value]
                supply_orders.append(MedicalSupplyOrder(
                    zone_id=f"zone_{pathogen.value}",
                    ors_sachets=pop_exposed // 5 if pathogen == Pathogen.CHOLERA else 0,
                    antibiotic_courses=pop_exposed // 10,
                    water_purification_tabs=pop_exposed // 2,
                    delivery_deadline=datetime.utcnow() + timedelta(hours=intervention_hours),
                    priority=1 if pathogen == Pathogen.CHOLERA else 2,
                ))

        all_cleared = all(h.risk_score < 0.7 for h in hotspots) if hotspots else True

        return DiseaseRiskReport(
            report_id=str(uuid.uuid4()),
            event_id=event_id,
            bbox=bbox,
            risk_maps=risk_maps,
            hotspots=hotspots,
            supply_orders=supply_orders,
            outbreak_risk_cleared=all_cleared,
        )
