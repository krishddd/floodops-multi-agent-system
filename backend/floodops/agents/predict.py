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
from typing import Any

from floodops.agents.base import BaseAgent, _as_dict
from floodops.config import (
    LEAD_TIME_SKILL_RETENTION,
    RETURN_PERIOD_BASE_F1,
    RETURN_PERIOD_DEPTH_THRESHOLDS_M,
    RETURN_PERIOD_MEMBER_AGREEMENT,
    SKILLFUL_F1_THRESHOLD,
)
from floodops.hydrology.return_periods import (
    annual_maxima,
    classify_return_period,
    compute_return_period_thresholds,
)
from floodops.llm.prompts import PREDICT_AGENT_SYSTEM_PROMPT
from floodops.models.causal import CausalGraph
from floodops.models.enums import TriggerType
from floodops.models.geo import BBox, GeoJsonFeatureCollection, GeoJsonGeometry
from floodops.models.predict import (
    EnsembleDisagreement,
    EnsembleMember,
    FloodDepthGrid,
    FloodForecast,
    FloodTiming,
    LeadTimeSkill,
    ProbabilisticFloodMap,
    ReturnPeriodEvent,
)
from floodops.models.reasoning import ReasonedAssessment


class FloodPredictAgent(BaseAgent):
    """Probabilistic flood forecasting engine.

    Key insight: run 10,000 scenarios from weather uncertainty, not just
    one best-guess forecast. The ensemble spread IS the uncertainty —
    and the UI visualizes it as spaghetti plots and probability fans
    instead of collapsing to a single number.
    """

    agent_id: str = "flood_predict_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Per-basin fitted return-period thresholds: (lat, lng) → (expiry, fit).
        self._rp_threshold_cache: dict[
            tuple[float, float], tuple[float, dict[int, float] | None]
        ] = {}
        # v5: per-basin runoff calibration: (lat, lng) → (expiry, result|None).
        self._calibration_cache: dict[
            tuple[float, float], tuple[float, dict | None]
        ] = {}

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

    async def run_ensemble(self, alert: dict[str, Any]) -> FloodForecast | None:
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

        # Real keyless meteorological forcing (Open-Meteo) biases the ensemble
        # intensity when a connector is wired; otherwise the deterministic mock is
        # used unchanged.
        intensity, rain_source = await self._forcing_intensity(bbox)

        # GloFAS benchmark reference: basin-specific return-period thresholds fit
        # from the 1984→present reanalysis, and where the benchmark's own forecast
        # lands against them. Reference only — never an input to our ensemble.
        bench_thresholds, bench_peak, bench_rp = await self._benchmark_return_period(bbox)

        # v4: physically-motivated ensemble — members route REAL perturbed
        # precipitation through a linear reservoir, with depth scaled by the
        # basin's fitted return-period thresholds. Mock kept as fallback.
        ensemble_members = None
        if bench_thresholds:
            ensemble_members = await self._generate_runoff_ensemble(
                bbox, 50, bench_thresholds
            )
        ensemble_source = "runoff-routed" if ensemble_members else "statistical-mock"
        if ensemble_members is None:
            ensemble_members = self._generate_mock_ensemble(bbox, 50, intensity=intensity)
        representative_ids = self._select_representatives(ensemble_members, k=10)

        # Aggregate into probability map
        prob_map = self._aggregate_to_probability_map(ensemble_members, watershed_id, bbox)
        timing = self._estimate_timing(ensemble_members)
        depth_grid = self._build_depth_grid(ensemble_members, watershed_id, bbox)
        disagreements = self._compute_disagreements(ensemble_members)
        rp_events, max_rp = self._classify_return_periods(ensemble_members)
        lead_skill, skillful_days = self._estimate_lead_time_skill(max_rp)

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
            causal_factors=([f"meteorological forcing ({rain_source})",
                             "antecedent soil moisture"]
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

        rp_clause = (
            f" Headline event: ~{max_rp}-yr return period."
            if max_rp is not None else " Below 1-yr return-period threshold."
        )
        if bench_thresholds is not None and bench_peak is not None:
            bench_label = f"~{bench_rp}-yr" if bench_rp is not None else "sub-1-yr"
            rp_clause += (
                f" GloFAS benchmark: peak {bench_peak:.0f} m³/s → {bench_label} event "
                f"(thresholds fit from {len(bench_thresholds)} return periods, "
                f"1984→present reanalysis)."
            )
        rp_clause += f" Ensemble: {ensemble_source}."
        if skillful_days is not None:
            rp_clause += f" Skillful warning horizon: {skillful_days} days."
        summary = (
            f"{assessment.summary}{rp_clause} "
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
            return_period_events=rp_events,
            max_return_period_years=max_rp,
            lead_time_skill=lead_skill,
            skillful_lead_days=skillful_days,
            benchmark_discharge_thresholds_m3s=bench_thresholds,
            benchmark_peak_discharge_m3s=bench_peak,
            benchmark_return_period_years=bench_rp,
            summary=summary,
        )
        return forecast

    async def run_glof_scenario(self, alert: dict[str, Any]) -> FloodForecast | None:
        """GLOF-specific forecast — skip rainfall ensemble, route breach volume."""
        # TODO: Implement breach volume routing through downstream DEM
        return await self.run_ensemble(alert)

    # ── Mock data generation (to be replaced with real models) ──────

    async def _forcing_intensity(self, bbox: BBox) -> tuple[float, str]:
        """Derive an ensemble-intensity multiplier from paper-faithful forcing.

        Combines two of the paper's input variables (Nearing et al. 2024) rather
        than precipitation alone: 72h precipitation **plus** a snowmelt term from
        positive-degree-hours (2-m temperature), which compounds flood risk in the
        Himalayan basin. GloFAS discharge is deliberately NOT used as an input.

        Returns (multiplier, source). Falls back to (1.0, "mock") with no connector
        or on any error, and to the precipitation-only path if the richer
        meteorology payload is unavailable — so behaviour degrades gracefully.
        """
        if self.connector is None:
            return 1.0, "mock"
        try:
            data = await self.connector.fetch_latest(bbox=bbox)
            data = data or {}
            met = data.get("meteorology") or {}

            if met:
                precip = float(met.get("precip_total_72h_mm") or 0.0)
                pdh = float(met.get("positive_degree_hours_72h") or 0.0)
                snow = float(met.get("snowfall_total_72h_cm") or 0.0)
                # Precip drives most of it (0–200mm → up to +1.3×). Snowmelt adds a
                # bounded term ONLY when there is snow in the forcing window — warm
                # temps alone (e.g. a hot lowland) are not melt. (Limitation: point
                # forecasts miss upstream glacial/snowpack melt, which needs basin
                # snow state we can't get keyless — documented in paper-alignment.md.)
                precip_term = precip / 150.0
                melt_term = min(0.4, pdh / 400.0) if snow > 0 else 0.0
                mult = max(0.7, min(2.0, 0.7 + precip_term + melt_term))
                src = f"openmeteo(precip {precip:.0f}mm/72h"
                src += f", melt +{melt_term:.2f})" if melt_term > 0 else ")"
                return round(mult, 2), src

            # Back-compat: precipitation-only payload.
            rain = data.get("rainfall") or {}
            total = float(rain.get("total_72h_mm") or 0.0)
            if total <= 0:
                return 1.0, "openmeteo(0mm)"
            mult = max(0.7, min(2.0, 0.7 + total / 150.0))
            return round(mult, 2), f"openmeteo({total:.0f}mm/72h)"
        except Exception as exc:
            self._logger.warning("forcing fetch failed: %s", exc)
            return 1.0, "mock"

    async def _benchmark_return_period(
        self, bbox: BBox
    ) -> tuple[dict[int, float] | None, float | None, int | None]:
        """Fit real basin return-period thresholds and classify the GloFAS forecast.

        Paper-aligned (Nearing et al. 2024): per-gauge return-period thresholds
        come from a flood-frequency fit on the historical record (Bulletin 17B),
        and forecast skill is framed by which return period an event reaches.
        Here the historical record is the keyless GloFAS reanalysis (1984→now)
        at the basin centre, and we classify the GloFAS *forecast* peak against
        the fitted thresholds — a benchmark reference, never an ensemble input.

        Returns ``(thresholds, forecast_peak_m3s, return_period_years)``; all
        None when no connector is wired, the record is too short (<10 yrs), or
        any fetch fails. Thresholds are cached per basin centre for 24h.
        """
        if self.connector is None or not hasattr(self.connector, "get_historical_discharge"):
            return None, None, None
        c = bbox.center()
        key = (round(c.lat, 2), round(c.lng, 2))
        try:
            cached = self._rp_threshold_cache.get(key)
            if cached is not None and cached[0] > datetime.utcnow().timestamp():
                thresholds = cached[1]
            else:
                hist = await self.connector.get_historical_discharge(c.lat, c.lng)
                if not hist:
                    return None, None, None
                maxima = annual_maxima(hist.get("time", []), hist.get("discharge", []))
                thresholds = compute_return_period_thresholds(list(maxima.values()))
                self._rp_threshold_cache[key] = (
                    datetime.utcnow().timestamp() + 86400, thresholds
                )
            if thresholds is None:
                return None, None, None

            forecast = await self.connector.get_discharge_ensemble(c.lat, c.lng)
            # Peak of the ensemble-mean trace (the max trace would overstate;
            # the mean mirrors how GloFAS exceedances are reported).
            mean_trace = [v for v in (forecast or {}).get("mean", []) if v is not None]
            if not mean_trace:
                return thresholds, None, None
            peak = max(mean_trace)
            rp = classify_return_period(peak, thresholds)
            return thresholds, round(peak, 1), rp
        except Exception as exc:
            self._logger.warning("benchmark return-period fit failed: %s", exc)
            return None, None, None

    def _extract_bbox(self, alert: dict[str, Any]) -> BBox:
        bbox_data = alert.get("bbox")
        if bbox_data and isinstance(bbox_data, dict):
            return BBox(**bbox_data)
        loc = alert.get("location", {})
        lat = loc.get("lat", 27.7)
        lng = loc.get("lng", 85.3)
        return BBox(south=lat - 0.5, west=lng - 0.5, north=lat + 0.5, east=lng + 0.5)

    async def _runoff_calibration(self, lat: float, lng: float,
                                  area_km2: float) -> dict | None:
        """Per-basin runoff scale calibration (v5), memoized for 24h.

        Pairs the keyless archive-precipitation and GloFAS-discharge
        reanalyses through hydrology/calibration.py. None (uncalibrated) when
        either record is unavailable or too short — never faked.
        """
        from floodops.config import RUNOFF_RECESSION_K
        from floodops.hydrology.calibration import calibrate_runoff_scale

        key = (round(lat, 2), round(lng, 2))
        cached = self._calibration_cache.get(key)
        if cached is not None and cached[0] > datetime.utcnow().timestamp():
            return cached[1]
        result: dict | None = None
        try:
            if hasattr(self.connector, "get_historical_precipitation"):
                precip = await self.connector.get_historical_precipitation(lat, lng)
                hist = await self.connector.get_historical_discharge(lat, lng)
                if precip and hist:
                    result = calibrate_runoff_scale(
                        precip.get("time", []), precip.get("precipitation", []),
                        hist.get("time", []), hist.get("discharge", []),
                        area_km2, recession_k=RUNOFF_RECESSION_K,
                    )
        except Exception as exc:
            self._logger.warning("runoff calibration failed: %s", exc)
        self._calibration_cache[key] = (
            datetime.utcnow().timestamp() + 86400, result
        )
        if result:
            self._logger.info(
                "runoff calibrated: scale=%.3f over %d paired years "
                "(IQR %.3f–%.3f)", result["scale"], result["paired_years"],
                result["ratio_p25"], result["ratio_p75"],
            )
        return result

    async def _generate_runoff_ensemble(
        self, bbox: BBox, n_members: int, discharge_thresholds: dict[int, float]
    ) -> list[EnsembleMember] | None:
        """Members that physically follow real rainfall (v4, see hydrology/runoff).

        Each member perturbs the real Open-Meteo daily precipitation
        (member-seeded uniform factor), routes it through a delayed linear
        reservoir, and converts its peak discharge to depth via the basin's
        fitted return-period scale. Deterministic given the forcing —
        uncalibrated physics, honestly labelled. Returns None when the
        forcing is unavailable (caller falls back to the statistical mock).
        """
        from floodops.config import (
            BASIN_EFFECTIVE_AREA_KM2,
            ENSEMBLE_SPREAD,
            RUNOFF_RECESSION_K,
        )
        from floodops.hydrology.runoff import (
            discharge_to_depth,
            perturb_precip,
            route_linear_reservoir,
            time_to_peak_hours,
        )

        if self.connector is None:
            return None
        try:
            c = bbox.center()
            rain = await self.connector.get_rainfall(c.lat, c.lng)
            series = (rain or {}).get("series") or []
            if len(series) < 24:
                return None
            # Hourly → daily totals (7 forecast days max).
            daily = [round(sum(series[d * 24:(d + 1) * 24]), 2)
                     for d in range(min(7, len(series) // 24))]
        except Exception as exc:
            self._logger.warning("runoff forcing fetch failed: %s", exc)
            return None
        if not daily:
            return None

        # Effective catchment area comes from config, NOT the alert bbox — the
        # bbox (~11,000 km² at 1°) is alert geometry; the GloFAS-cell thresholds
        # describe the actual river catchment (config default ≈ upper Bagmati).
        area_km2 = BASIN_EFFECTIVE_AREA_KM2
        tp_h = time_to_peak_hours(area_km2)

        # v5: per-basin magnitude calibration against the reanalysis (None →
        # uncalibrated v4 behaviour, honestly labelled in the log).
        calibration = await self._runoff_calibration(c.lat, c.lng, area_km2)
        scale = float(calibration["scale"]) if calibration else 1.0

        import random
        center_lat = (bbox.south + bbox.north) / 2
        center_lng = (bbox.west + bbox.east) / 2
        now = datetime.utcnow()
        members: list[EnsembleMember] = []
        for i in range(n_members):
            perturbed = perturb_precip(daily, i, spread=ENSEMBLE_SPREAD)
            trace = route_linear_reservoir(
                perturbed, area_km2, recession_k=RUNOFF_RECESSION_K
            )
            peak_q = (max(trace) if trace else 0.0) * scale
            peak_day = trace.index(max(trace)) if trace else 0
            depth = max(0.05, discharge_to_depth(peak_q, discharge_thresholds))

            if depth > 3.0:
                category = "catastrophic"
            elif depth > 1.0:
                category = "severe"
            elif depth > 0.5:
                category = "moderate"
            else:
                category = "minimal"

            rng = random.Random(i)
            offset = rng.gauss(0, 0.02 * (i % 5 + 1))
            front_coords = [
                [center_lng - 0.3 + offset, center_lat - 0.2 + offset * 0.5],
                [center_lng - 0.1 + offset * 0.7, center_lat + 0.1 - offset * 0.3],
                [center_lng + 0.2 + offset * 1.2, center_lat + 0.15 + offset * 0.8],
                [center_lng + 0.4 + offset * 0.5, center_lat - 0.05 + offset * 0.2],
            ]
            members.append(EnsembleMember(
                member_id=i,
                flood_front=GeoJsonGeometry(type="LineString", coordinates=front_coords),
                peak_depth_m=round(depth, 2),
                peak_time=now + timedelta(hours=peak_day * 24 + tp_h),
                flood_extent_km2=round(max(0.0, depth * 15 + rng.gauss(0, 5)), 1),
                outcome_category=category,
            ))
        self._logger.info(
            "runoff ensemble: %d members from %d-day real forcing "
            "(area %.0f km², tp %.1f h, %s)", n_members, len(daily), area_km2,
            tp_h,
            (f"calibrated scale {scale:.3f}" if calibration
             else "UNCALIBRATED scale 1.0"),
        )
        return members

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

    def _classify_return_periods(
        self, members: list[EnsembleMember]
    ) -> tuple[list[ReturnPeriodEvent], int | None]:
        """Compute per-return-period exceedance across the ensemble.

        Paper-aligned (Nearing et al., Nature 627, 2024): for each return period
        threshold, count the fraction of members whose peak depth exceeds it. The
        headline ``max_rp`` is the largest return period that at least
        ``RETURN_PERIOD_MEMBER_AGREEMENT`` of members agree on. Fully deterministic
        — this never touches the LLM, so it is safe to drive downstream routing.
        """
        if not members:
            return [], None

        n = len(members)
        depths = [m.peak_depth_m for m in members]
        events: list[ReturnPeriodEvent] = []
        max_rp: int | None = None

        for rp_years in sorted(RETURN_PERIOD_DEPTH_THRESHOLDS_M):
            threshold = RETURN_PERIOD_DEPTH_THRESHOLDS_M[rp_years]
            count = sum(1 for d in depths if d >= threshold)
            prob = count / n
            events.append(ReturnPeriodEvent(
                return_period_years=rp_years,
                threshold_depth_m=threshold,
                exceedance_probability=round(prob, 2),
                member_count=count,
            ))
            if prob >= RETURN_PERIOD_MEMBER_AGREEMENT:
                max_rp = rp_years

        return events, max_rp

    def _estimate_lead_time_skill(
        self, max_rp: int | None
    ) -> tuple[list[LeadTimeSkill], int | None]:
        """Estimate how forecast reliability decays across the 7-day horizon.

        Paper-aligned (Nearing et al., Nature 627, 2024): AI skill is retained to
        ~5-day lead time, enabling earlier warnings. We scale a reference nowcast
        F1 (keyed to the headline return period — rarer events score lower) by the
        configured per-lead-day retention curve, and report the ``skillful_days``
        warning horizon as the furthest lead time whose estimated F1 clears
        ``SKILLFUL_F1_THRESHOLD``. Deterministic — never LLM-gated.
        """
        # Headline return period drives the base reliability; default to the
        # 1-yr (most reliable) reference when the ensemble is below threshold.
        rp_key = max_rp if max_rp in RETURN_PERIOD_BASE_F1 else 1
        base_f1 = RETURN_PERIOD_BASE_F1[rp_key]

        skill: list[LeadTimeSkill] = []
        skillful_days: int | None = None
        for lead_days, retention in enumerate(LEAD_TIME_SKILL_RETENTION):
            est_f1 = round(base_f1 * retention, 3)
            skill.append(LeadTimeSkill(
                lead_time_days=lead_days,
                estimated_f1=est_f1,
                skill_retention=retention,
            ))
            if est_f1 >= SKILLFUL_F1_THRESHOLD:
                skillful_days = lead_days

        return skill, skillful_days

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
