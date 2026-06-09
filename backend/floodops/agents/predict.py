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

from floodops.agents.base import BaseAgent, _as_dict
from floodops.llm.prompts import PREDICT_AGENT_SYSTEM_PROMPT
from floodops.models.causal import CausalGraph
from floodops.models.enums import AlertLevel, TriggerType
from floodops.models.reasoning import ReasonedAssessment
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
        await self.event_bus.subscribe("anomaly_alerts", self.handle_anomaly)
        await self.event_bus.subscribe("glof_alerts", self.handle_glof_alert)
        self.log_action("initialize", "FloodPredictAgent subscribed to anomaly_alerts and glof_alerts", 1.0)

    async def handle_event(self, channel: str, payload: Any) -> None:
        """Required by BaseAgent. We subscribe to specific handlers instead."""
        pass

    async def handle_anomaly(self, channel: str, alert: Any) -> None:
        """Process an anomaly alert from SentinelAgent."""
        alert = _as_dict(alert)
        forecast = await self.run_ensemble(alert)
        if forecast:
            await self.event_bus.emit("flood_forecasts", forecast.model_dump())
            self.log_action(
                "emit_forecast",
                f"Emitted flood forecast with max_probability={forecast.max_probability:.2f} "
                f"for watershed {forecast.watershed_id}",
                forecast.max_probability,
            )

    async def handle_glof_alert(self, channel: str, alert: Any) -> None:
        """Process a GLOF probabilistic alert (not emergency bypass)."""
        alert = _as_dict(alert)
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

        # Real keyless rainfall (Open-Meteo) biases the ensemble intensity when a
        # connector is wired; otherwise the deterministic mock is used unchanged.
        intensity, rain_source = await self._rainfall_intensity(bbox)

        ensemble_members = self._generate_mock_ensemble(bbox, 50, intensity=intensity)
        representative_ids = self._select_representatives(ensemble_members, k=10)

        # Aggregate into probability map
        prob_map = self._aggregate_to_probability_map(ensemble_members, watershed_id, bbox)
        timing = self._estimate_timing(ensemble_members)
        depth_grid = self._build_depth_grid(ensemble_members, watershed_id, bbox)
        disagreements = self._compute_disagreements(ensemble_members)

        # Deterministic ensemble probability drives phase routing (safety —
        # the LLM never overrides this number).
        max_prob = prob_map.max_probability

        # ── Core-3: uncertainty quantification + ensemble-vote reasoning ──
        depths = [m.peak_depth_m for m in ensemble_members]
        bounds = self._quantify_uncertainty(depths, ensemble_spread=depths)

        det_summary = (
            f"Ensemble forecast: {max_prob:.0%} max probability, peak in "
            f"{timing.confidence_interval_hours:.0f}h (±{timing.confidence_interval_hours:.0f}h). "
            f"Agreement: {disagreements[0].agreement_strength:.0%} on "
            f"{disagreements[0].dominant_outcome} outcome."
            if disagreements else f"Ensemble forecast: {max_prob:.0%} max probability."
        )
        # Mock assessment = deterministic result; LLM (if keyed) refines summary.
        top = disagreements[0] if disagreements else None
        competing = (
            "Rainfall could shift, reducing impact to minor flooding"
            if top and top.minimal_pct > 0.2 else None
        )
        mock_assessment = ReasonedAssessment(
            agent_id=self.agent_id,
            value=max_prob,
            confidence=max(0.1, top.agreement_strength if top else 0.5),
            summary=det_summary,
            causal_factors=([f"rainfall ({rain_source})", "antecedent soil moisture"]
                            + CausalGraph.from_config().ranked_causal_factors()[:3]),
            competing_hypothesis=competing,
        )
        assessment = await self._ensemble_vote(
            system=PREDICT_AGENT_SYSTEM_PROMPT,
            data={
                "watershed_id": watershed_id,
                "member_peak_depths_m": [round(d, 2) for d in depths],
                "outcome_breakdown": disagreements[0].model_dump() if disagreements else {},
                "deterministic_max_probability": max_prob,
                "peak_eta_hours": timing.confidence_interval_hours,
            },
            context={"depth_p5_p95": [round(bounds.aleatoric_low, 2),
                                      round(bounds.aleatoric_high, 2)]},
            schema=ReasonedAssessment,
            mock=mock_assessment,
        )

        summary = (
            f"{assessment.summary} "
            f"[depth 90% CI {max(0.0, bounds.aleatoric_low):.2f}–"
            f"{bounds.aleatoric_high:.2f}m, "
            f"reasoning confidence {assessment.confidence:.0%}]"
        )

        # Agent memory: recall the closest historical analogue (if recall is
        # enabled) and remember this forecast for future events.
        analogues = self.recall_similar(
            f"flood {watershed_id} probability {max_prob:.0%} rainfall {rain_source}"
        )
        if analogues:
            top = analogues[0]
            summary += f" Closest historical analogue: {top.summary} (sim {top.similarity})."
        self.remember(
            f"Flood {watershed_id}: {max_prob:.0%} probability, {rain_source}, "
            f"dominant {disagreements[0].dominant_outcome if disagreements else 'n/a'}.",
            {"watershed_id": watershed_id, "max_probability": max_prob},
        )

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
            summary=summary,
        )
        return forecast

    async def run_glof_scenario(self, alert: dict[str, Any]) -> Optional[FloodForecast]:
        """GLOF-specific forecast — skip rainfall ensemble, route breach volume."""
        # TODO: Implement breach volume routing through downstream DEM
        return await self.run_ensemble(alert)

    # ── Mock data generation (to be replaced with real models) ──────

    async def _rainfall_intensity(self, bbox: BBox) -> tuple[float, str]:
        """Derive an ensemble-intensity multiplier from real rainfall.

        Uses the injected connector's Open-Meteo 72h rainfall total. Returns
        (multiplier, source). Falls back to (1.0, "mock") with no connector or
        on any error — so behaviour is unchanged without live data.
        """
        if self.connector is None:
            return 1.0, "mock"
        try:
            data = await self.connector.fetch_latest(bbox=bbox)
            rain = (data or {}).get("rainfall") or {}
            total = float(rain.get("total_72h_mm") or 0.0)
            if total <= 0:
                return 1.0, "openmeteo(0mm)"
            # Map 0–200mm/72h → ~0.7–2.0× intensity (saturating).
            mult = max(0.7, min(2.0, 0.7 + total / 150.0))
            return round(mult, 2), f"openmeteo({total:.0f}mm/72h)"
        except Exception as exc:
            self._logger.warning("rainfall fetch failed: %s", exc)
            return 1.0, "mock"

    def _extract_bbox(self, alert: dict[str, Any]) -> BBox:
        bbox_data = alert.get("bbox")
        if bbox_data and isinstance(bbox_data, dict):
            return BBox(**bbox_data)
        loc = alert.get("location", {})
        lat = loc.get("lat", 27.7)
        lng = loc.get("lng", 85.3)
        return BBox(south=lat - 0.5, west=lng - 0.5, north=lat + 0.5, east=lng + 0.5)

    def _generate_mock_ensemble(
        self, bbox: BBox, n_members: int, intensity: float = 1.0
    ) -> list[EnsembleMember]:
        """Generate statistically realistic ensemble members.

        Creates a spread of outcomes — some catastrophic, most moderate,
        a few minimal — to demonstrate spaghetti plot divergence. ``intensity``
        (derived from real rainfall when a connector is wired) scales peak depths.
        """
        import random
        random.seed(42)

        center_lat = (bbox.south + bbox.north) / 2
        center_lng = (bbox.west + bbox.east) / 2
        members = []

        for i in range(n_members):
            # Vary peak depth across members (log-normal-like distribution),
            # scaled by real-rainfall intensity when available.
            depth_factor = random.lognormvariate(0.5, 0.8) * intensity
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
