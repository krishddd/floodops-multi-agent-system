"""
FloodPredictAgent — Probabilistic flood forecasting engine.

Converts sensor anomalies into spatial probability estimates by running
Monte Carlo scenarios through watershed hydraulic models. This agent
produces the RICHEST data in the system — the full ensemble is preserved
for spaghetti plots, probability fans, and disagreement badges.

Trigger: Queue from SentinelAgent or GLOFAgent anomaly alerts.
Emits: FloodForecast → flood_forecasts queue
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from floodops.agents.base import BaseAgent
from floodops.models.enums import AlertLevel, TriggerType
from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonFeature, GeoJsonGeometry
from floodops.models.predict import (
    EnsembleDisagreement,
    EnsembleMember,
    FloodDepthGrid,
    FloodForecast,
    FloodTiming,
    ProbabilisticFloodMap,
)
from floodops.models.sentinel import AnomalyAlert


class FloodPredictAgent(BaseAgent):
    """Probabilistic flood forecasting engine.

    Key insight: run 10,000 scenarios from weather uncertainty, not just
    one best-guess forecast. The ensemble spread IS the uncertainty —
    and the UI visualizes it as spaghetti plots and probability fans
    instead of collapsing to a single number.
    """

    agent_id: str = "flood_predict_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE]

    async def initialize(self) -> None:
        """Subscribe to anomaly_alerts and glof_alerts queues."""
        self.event_bus.subscribe("anomaly_alerts", self.handle_anomaly)
        self.event_bus.subscribe("glof_alerts", self.handle_glof_alert)
        await self.log_action("initialize", "FloodPredictAgent subscribed to anomaly_alerts and glof_alerts", 1.0)

    async def handle_anomaly(self, alert: dict[str, Any]) -> None:
        """Process an anomaly alert from SentinelAgent."""
        forecast = await self.run_ensemble(alert)
        if forecast:
            await self.event_bus.emit("flood_forecasts", forecast.model_dump())
            await self.log_action(
                "emit_forecast",
                f"Emitted flood forecast with max_probability={forecast.max_probability:.2f} "
                f"for watershed {forecast.watershed_id}",
                forecast.max_probability,
            )

    async def handle_glof_alert(self, alert: dict[str, Any]) -> None:
        """Process a GLOF probabilistic alert (not emergency bypass)."""
        forecast = await self.run_glof_scenario(alert)
        if forecast:
            await self.event_bus.emit("flood_forecasts", forecast.model_dump())

    async def run_ensemble(self, alert: dict[str, Any]) -> Optional[FloodForecast]:
        """Run Monte Carlo ensemble flood model.

        Steps:
        1. Fetch ECMWF 50-member weather ensemble for the watershed bbox
        2. For each ensemble member, sample soil moisture uncertainty
        3. Route rainfall through watershed DEM (simplified hydraulic model)
        4. Aggregate 10,000 scenarios into probability map
        5. Apply ML bias-correction model
        6. Preserve individual member data for UI spaghetti/fan/disagreement

        TODO: Implement actual hydraulic routing. Currently generates mock
        ensemble data with realistic statistical properties.
        """
        watershed_id = alert.get("watershed_id", "unknown")
        bbox = self._extract_bbox(alert)

        # --- STUB: Generate realistic ensemble data ---
        ensemble_members = self._generate_mock_ensemble(bbox, 50)
        representative_ids = self._select_representatives(ensemble_members, k=10)

        # Aggregate into probability map
        prob_map = self._aggregate_to_probability_map(ensemble_members, watershed_id, bbox)
        timing = self._estimate_timing(ensemble_members)
        depth_grid = self._build_depth_grid(ensemble_members, watershed_id, bbox)
        disagreements = self._compute_disagreements(ensemble_members)

        max_prob = prob_map.max_probability

        forecast = FloodForecast(
            forecast_id=str(uuid.uuid4()),
            event_id=alert.get("alert_id", str(uuid.uuid4())),
            watershed_id=watershed_id,
            bbox=bbox,
            probability_map=prob_map,
            timing=timing,
            depth_grid=depth_grid,
            max_probability=max_prob,
            ensemble_members=ensemble_members,
            representative_members=representative_ids,
            zone_disagreements=disagreements,
            summary=f"Ensemble forecast: {max_prob:.0%} max probability, "
                    f"peak in {timing.confidence_interval_hours:.0f}h (±{timing.confidence_interval_hours:.0f}h). "
                    f"Agreement: {disagreements[0].agreement_strength:.0%} on {disagreements[0].dominant_outcome} outcome."
                    if disagreements else None,
        )
        return forecast

    async def run_glof_scenario(self, alert: dict[str, Any]) -> Optional[FloodForecast]:
        """GLOF-specific forecast — skip rainfall ensemble, route breach volume."""
        # TODO: Implement breach volume routing through downstream DEM
        return await self.run_ensemble(alert)

    # ── Mock data generation (to be replaced with real models) ──────

    def _extract_bbox(self, alert: dict[str, Any]) -> BBox:
        bbox_data = alert.get("bbox")
        if bbox_data and isinstance(bbox_data, dict):
            return BBox(**bbox_data)
        loc = alert.get("location", {})
        lat = loc.get("lat", 27.7)
        lng = loc.get("lng", 85.3)
        return BBox(south=lat - 0.5, west=lng - 0.5, north=lat + 0.5, east=lng + 0.5)

    def _generate_mock_ensemble(self, bbox: BBox, n_members: int) -> list[EnsembleMember]:
        """Generate statistically realistic ensemble members.

        Creates a spread of outcomes — some catastrophic, most moderate,
        a few minimal — to demonstrate spaghetti plot divergence.
        """
        import random
        random.seed(42)

        center_lat = (bbox.south + bbox.north) / 2
        center_lng = (bbox.west + bbox.east) / 2
        members = []

        for i in range(n_members):
            # Vary peak depth across members (log-normal-like distribution)
            depth_factor = random.lognormvariate(0.5, 0.8)
            peak_depth = min(max(depth_factor, 0.1), 8.0)

            # Classify outcome
            if peak_depth > 3.0:
                category = "catastrophic"
            elif peak_depth > 1.0:
                category = "severe"
            elif peak_depth > 0.5:
                category = "moderate"
            else:
                category = "minimal"

            # Vary flood front position per member (spaghetti divergence)
            offset = random.gauss(0, 0.02 * (i % 5 + 1))
            front_coords = [
                [center_lng - 0.3 + offset, center_lat - 0.2 + offset * 0.5],
                [center_lng - 0.1 + offset * 0.7, center_lat + 0.1 - offset * 0.3],
                [center_lng + 0.2 + offset * 1.2, center_lat + 0.15 + offset * 0.8],
                [center_lng + 0.4 + offset * 0.5, center_lat - 0.05 + offset * 0.2],
            ]

            peak_time = datetime.utcnow() + timedelta(hours=random.gauss(18, 6))

            members.append(EnsembleMember(
                member_id=i,
                flood_front=GeoJsonGeometry(type="LineString", coordinates=front_coords),
                peak_depth_m=round(peak_depth, 2),
                peak_time=peak_time,
                flood_extent_km2=round(peak_depth * 15 + random.gauss(0, 5), 1),
                outcome_category=category,
            ))

        return members

    def _select_representatives(self, members: list[EnsembleMember], k: int) -> list[int]:
        """Select k representative members via simplified k-means on peak depth."""
        if len(members) <= k:
            return [m.member_id for m in members]

        sorted_members = sorted(members, key=lambda m: m.peak_depth_m)
        step = len(sorted_members) // k
        return [sorted_members[i * step].member_id for i in range(k)]

    def _aggregate_to_probability_map(
        self, members: list[EnsembleMember], watershed_id: str, bbox: BBox
    ) -> ProbabilisticFloodMap:
        """Aggregate ensemble into spatial probability map."""
        max_prob = 0.0
        if members:
            # Fraction of members predicting significant flooding
            significant = sum(1 for m in members if m.peak_depth_m > 0.5)
            max_prob = round(significant / len(members), 2)

        return ProbabilisticFloodMap(
            watershed_id=watershed_id,
            bbox=bbox,
            cell_probabilities=GeoJsonFeatureCollection(features=[]),
            max_probability=max_prob,
        )

    def _estimate_timing(self, members: list[EnsembleMember]) -> FloodTiming:
        """Estimate peak timing with uncertainty from ensemble spread."""
        if not members:
            now = datetime.utcnow()
            return FloodTiming(
                peak_time=now + timedelta(hours=24),
                confidence_interval_hours=12,
                earliest_peak=now + timedelta(hours=12),
                latest_peak=now + timedelta(hours=36),
            )

        peak_times = sorted(m.peak_time for m in members)
        median_idx = len(peak_times) // 2
        p5_idx = max(0, len(peak_times) // 20)
        p95_idx = min(len(peak_times) - 1, len(peak_times) * 19 // 20)

        median_peak = peak_times[median_idx]
        earliest = peak_times[p5_idx]
        latest = peak_times[p95_idx]
        interval = (latest - earliest).total_seconds() / 3600 / 2

        return FloodTiming(
            peak_time=median_peak,
            confidence_interval_hours=round(interval, 1),
            earliest_peak=earliest,
            latest_peak=latest,
        )

    def _build_depth_grid(
        self, members: list[EnsembleMember], watershed_id: str, bbox: BBox
    ) -> FloodDepthGrid:
        """Build depth grid with percentile bounds for 3D extrusion."""
        return FloodDepthGrid(
            watershed_id=watershed_id,
            bbox=bbox,
            cells=GeoJsonFeatureCollection(features=[]),
        )

    def _compute_disagreements(self, members: list[EnsembleMember]) -> list[EnsembleDisagreement]:
        """Compute per-zone ensemble disagreement for badges."""
        if not members:
            return []

        n = len(members)
        cats = {"catastrophic": 0, "severe": 0, "moderate": 0, "minimal": 0}
        for m in members:
            cats[m.outcome_category] = cats.get(m.outcome_category, 0) + 1

        dominant = max(cats, key=cats.get)
        agreement = cats[dominant] / n

        return [EnsembleDisagreement(
            zone_id="zone_default",
            catastrophic_pct=round(cats["catastrophic"] / n, 2),
            severe_pct=round(cats["severe"] / n, 2),
            moderate_pct=round(cats["moderate"] / n, 2),
            minimal_pct=round(cats["minimal"] / n, 2),
            dominant_outcome=dominant,
            agreement_strength=round(agreement, 2),
        )]
