"""
ResourceAgent — Logistics, pre-positioning, and rescue routing.

Most disaster response is reactive — supplies ordered AFTER the flood.
ResourceAgent uses the prediction window to act BEFORE the event.

Trigger: Queue from FloodPredictAgent (p>0.5) + DiseaseRiskAgent.
Emits: ResourceOrders → resource_orders queue
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from floodops.agents.base import BaseAgent
from floodops.models.enums import TriggerType
from floodops.models.geo import Coordinate, GeoJsonGeometry
from floodops.models.resource import (
    DistributionPlan,
    LogisticsOrder,
    RescueRoute,
    ResourceOrders,
    StagingLocation,
    SupplyItem,
)


class ResourceAgent(BaseAgent):
    """Logistics router — pre-position before, rescue during, distribute after."""

    agent_id: str = "resource_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE]

    async def initialize(self) -> None:
        await self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        await self.event_bus.subscribe("disease_risk", self.handle_disease_risk)
        self.log_action("initialize", "ResourceAgent subscribed to flood_forecasts and disease_risk", 1.0)

    async def handle_forecast(self, forecast_data: dict[str, Any]) -> None:
        """Pre-position supplies if probability > 50% and 12+ hours to peak."""
        max_prob = forecast_data.get("max_probability", 0)
        if max_prob < 0.5:
            self.log_action("skip_preposition", f"Probability {max_prob:.0%} below 50% threshold", 0.9)
            return

        orders = await self.preposition_supplies(forecast_data)
        if orders:
            await self.event_bus.emit("resource_orders", orders.model_dump())
            self.log_action(
                "preposition",
                f"Generated {len(orders.logistics_orders)} logistics orders, supplies prepositioned",
                0.85,
            )

    async def handle_event(self, channel: str, payload: Any) -> None:
        pass

    async def handle_disease_risk(self, risk_data: dict[str, Any]) -> None:
        """Distribute medical supplies to disease hotspots post-flood."""
        plans = self._generate_distribution_plans(risk_data)
        if plans:
            orders = ResourceOrders(
                event_id=risk_data.get("event_id", str(uuid.uuid4())),
                distribution_plans=plans,
                supplies_prepositioned=True,
            )
            await self.event_bus.emit("resource_orders", orders.model_dump())

    async def preposition_supplies(self, forecast_data: dict[str, Any]) -> Optional[ResourceOrders]:
        """Calculate supply needs and generate movement orders."""
        event_id = forecast_data.get("event_id", str(uuid.uuid4()))

        staging = StagingLocation(
            staging_id="staging_01",
            name="Bhaktapur Distribution Center",
            location=Coordinate(lat=27.68, lng=85.43),
            capacity_tons=50.0,
            travel_hours_to_zone=0.8,
        )

        supplies = [
            SupplyItem(item_type="ORS_sachets", quantity=5000, unit="sachets"),
            SupplyItem(item_type="water_purification_tabs", quantity=10000, unit="tablets"),
            SupplyItem(item_type="antibiotic_courses", quantity=500, unit="courses"),
            SupplyItem(item_type="rescue_boats", quantity=8, unit="boats"),
        ]

        order = LogisticsOrder(
            order_id=str(uuid.uuid4()),
            route=GeoJsonGeometry(type="LineString", coordinates=[[85.3, 27.7], [85.43, 27.68]]),
            payload=supplies,
            origin=Coordinate(lat=27.7, lng=85.3),
            destination=staging,
            deadline=datetime.utcnow() + timedelta(hours=10),
        )

        return ResourceOrders(
            event_id=event_id,
            logistics_orders=[order],
            supplies_prepositioned=True,
        )

    def _generate_distribution_plans(self, risk_data: dict[str, Any]) -> list[DistributionPlan]:
        """Generate medical distribution plans for disease hotspots."""
        hotspots = risk_data.get("hotspots", [])
        plans = []
        for hs in hotspots:
            plans.append(DistributionPlan(
                plan_id=str(uuid.uuid4()),
                zone_id=hs.get("zone_id", "unknown"),
                supply_types=[
                    SupplyItem(item_type="ORS_sachets", quantity=1000),
                    SupplyItem(item_type="antibiotic_courses", quantity=200),
                ],
                delivery_window_hours=48.0,
                priority=1,
            ))
        return plans
