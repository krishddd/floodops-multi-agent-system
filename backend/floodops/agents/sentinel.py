"""
SentinelAgent — the watchful eye.

SentinelAgent is the base data-ingestion layer. It polls raw sensor APIs
(NOAA weather radar, USGS stream gauges, ESA soil moisture) on CRON
schedules and performs z-score anomaly detection against rolling baselines.

Trigger: CRON (every 15 minutes for weather/gauges)
Emits:   "anomaly_alerts" → FloodPredictAgent, GLOFAgent
         "flood_receding" → DiseaseRiskAgent

Data flow::

    NOAA API ──┐
    USGS API ──┼──► SentinelAgent ──z-score──► anomaly_alerts queue
    ESA API  ──┘                            └──► flood_receding queue

Anomaly detection algorithm:
    1. Fetch latest sensor readings for each watershed
    2. Compare against 30-day rolling baseline (mean, std)
    3. Compute z-score = (value - mean) / std
    4. If |z| > threshold AND 2+ sensors agree → emit AnomalyAlert
    5. Multi-sensor agreement reduces false positive rate
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from floodops.agents.base import BaseAgent
from floodops.config import (
    ANOMALY_THRESHOLDS,
    BASIN_BBOX_HALF_DEG,
    BASIN_CENTER_LAT,
    BASIN_CENTER_LNG,
    CRON_SENTINEL_GAUGES,
    CRON_SENTINEL_WEATHER,
    DEESCALATION_GAUGE_HOURS,
)
from floodops.models.enums import AlertLevel, DataSource, FloodPhase, TriggerType
from floodops.models.geo import BBox, Coordinate
from floodops.models.sentinel import AnomalyAlert, Baseline, FloodRecedingEvent, SensorReading
from floodops.queue.event_bus import EventBus

logger = logging.getLogger(__name__)


class SentinelAgent(BaseAgent):
    """Polls sensor APIs and detects anomalies via z-score deviation.

    Internal state:
        _baselines: Rolling baselines per (watershed_id, metric).
        _recent_readings: Buffer of recent readings for multi-sensor correlation.
        _gauge_history: Per-gauge recent levels for recession detection.
    """

    agent_id: str = "sentinel_agent"
    trigger_types: set[TriggerType] = {TriggerType.CRON}

    def __init__(self, event_bus: EventBus, llm=None, connector=None,
                 gdacs=None) -> None:
        super().__init__(event_bus, llm, connector)
        # Baselines keyed by (watershed_id, metric)
        self._baselines: dict[tuple[str, str], Baseline] = {}
        # Recent readings for multi-sensor correlation
        self._recent_readings: list[SensorReading] = []
        # Gauge history for recession detection: gauge_id → list[(timestamp, value)]
        self._gauge_history: dict[str, list[tuple[datetime, float]]] = {}
        # v4: optional GDACS connector for independent cross-validation.
        self.gdacs = gdacs
        # Dedup of already-emitted GDACS event ids (per process).
        self._gdacs_seen: set[str] = set()

    async def initialize(self) -> None:
        """Register CRON jobs for weather, gauge, and GDACS polling."""
        await self.event_bus.register_cron(
            CRON_SENTINEL_WEATHER,
            self._poll_weather,
            job_id="sentinel_weather",
        )
        await self.event_bus.register_cron(
            CRON_SENTINEL_GAUGES,
            self._poll_gauges,
            job_id="sentinel_gauges",
        )
        if self.gdacs is not None:
            await self.event_bus.register_cron(
                CRON_SENTINEL_WEATHER,
                self._poll_gdacs,
                job_id="sentinel_gdacs",
            )
        self._logger.info("SentinelAgent initialised with CRON polling")

    async def handle_event(self, channel: str, payload: Any) -> None:
        """SentinelAgent is CRON-triggered, not event-triggered.

        This handler exists for manual re-scan requests from the API.
        """
        if channel == "sentinel_rescan":
            await self._poll_weather()
            await self._poll_gauges()

    # ── CRON handlers ────────────────────────────────────────────────

    async def _poll_weather(self) -> None:
        """Fetch latest weather data from NOAA/NWS and check for anomalies.

        STUB: In production, calls NOAAConnector.get_latest_observations()
        and compares against baselines. Here we demonstrate the full
        detection pipeline with the correct types.
        """
        self._logger.info("Polling weather data (NOAA/NWS)")

        # --- STUB: Replace with real connector call ---
        # readings = await self.noaa_connector.get_latest_observations(bbox)
        readings = self._generate_stub_readings("rainfall_mm", DataSource.NWS_ALERTS)
        # --- END STUB ---

        for reading in readings:
            self._recent_readings.append(reading)
            anomaly = self._detect_anomaly(reading)
            if anomaly is not None:
                await self.event_bus.emit("anomaly_alerts", anomaly.model_dump())
                self.log_action(
                    action="emit_anomaly_alert",
                    reasoning=(
                        f"Rainfall reading of {reading.value:.1f}{reading.unit} at "
                        f"sensor {reading.sensor_id} is {anomaly.deviation_sigma:.1f}σ "
                        f"above 30-day mean. {anomaly.agreeing_sensors}/{anomaly.total_sensors} "
                        f"sensors in watershed {reading.watershed_id} confirm anomaly."
                    ),
                    confidence=anomaly.confidence,
                    phase=FloodPhase.MONITORING,
                    input_summary=f"sensor={reading.sensor_id} value={reading.value}",
                    output_summary=f"alert_level={anomaly.level.value}",
                    data_sources=["NOAA_NWS:15min"],
                )

        # Trim old readings (keep last 2 hours)
        cutoff = datetime.utcnow() - timedelta(hours=2)
        self._recent_readings = [r for r in self._recent_readings if r.timestamp > cutoff]

    async def _poll_gauges(self) -> None:
        """Fetch latest USGS stream gauge data and check for anomalies / recession.

        STUB: In production, calls USGSConnector.get_instantaneous_values()
        """
        self._logger.info("Polling gauge data (USGS)")

        # --- STUB: Replace with real connector call ---
        readings = self._generate_stub_readings("water_level_m", DataSource.USGS_GAUGES)
        # --- END STUB ---

        for reading in readings:
            self._recent_readings.append(reading)

            # Track gauge history for recession detection
            gauge_key = reading.sensor_id
            if gauge_key not in self._gauge_history:
                self._gauge_history[gauge_key] = []
            self._gauge_history[gauge_key].append((reading.timestamp, reading.value))
            # Keep last 24 hours
            cutoff = datetime.utcnow() - timedelta(hours=24)
            self._gauge_history[gauge_key] = [
                (t, v) for t, v in self._gauge_history[gauge_key] if t > cutoff
            ]

            # Anomaly detection
            anomaly = self._detect_anomaly(reading)
            if anomaly is not None:
                await self.event_bus.emit("anomaly_alerts", anomaly.model_dump())

        # Check for flood recession
        await self._check_recession()

    async def _poll_gdacs(self) -> None:
        """Cross-validate against GDACS global flood alerts (v4, keyless).

        Two deterministic outputs (never LLM-gated):
          * every active flood event → ``external_hazards`` (independent
            confirmation signal consumed by the CompoundEventAgent);
          * an Orange/Red event whose bbox intersects the basin bbox
            (rectangle approximation, WGS84) → an ``anomaly_alerts`` boost,
            because an independent global system confirms flooding here.
        """
        if self.gdacs is None:
            return
        try:
            events = await self.gdacs.get_flood_events()
        except Exception as exc:
            self._logger.warning("GDACS poll failed: %s", exc)
            return
        if not events:
            return

        basin_bbox = BBox(
            south=BASIN_CENTER_LAT - BASIN_BBOX_HALF_DEG,
            west=BASIN_CENTER_LNG - BASIN_BBOX_HALF_DEG,
            north=BASIN_CENTER_LAT + BASIN_BBOX_HALF_DEG,
            east=BASIN_CENTER_LNG + BASIN_BBOX_HALF_DEG,
        )
        for event in events:
            event_id = event.get("event_id") or ""
            if not event_id or event_id in self._gdacs_seen:
                continue
            self._gdacs_seen.add(event_id)
            await self.event_bus.emit("external_hazards", {
                "source": "GDACS",
                "event_id": event_id,
                "name": event.get("name", ""),
                "alert_level": event.get("alert_level", "green"),
                "severity": float(event.get("severity", 0.3)),
                "bbox": event.get("bbox"),
                "from_date": event.get("from_date"),
                "report_url": event.get("report_url"),
            })

            overlaps = (
                event.get("bbox")
                and self.gdacs._intersects(basin_bbox, event["bbox"])
            )
            if overlaps and event.get("alert_level") in ("orange", "red"):
                level = (AlertLevel.CRITICAL if event["alert_level"] == "red"
                         else AlertLevel.HIGH)
                alert = AnomalyAlert(
                    alert_id=str(uuid.uuid4()),
                    level=level,
                    metric="external_flood_confirmation",
                    value=float(event.get("severity", 0.6)),
                    deviation_sigma=ANOMALY_THRESHOLDS[level.value],
                    location=Coordinate(lat=BASIN_CENTER_LAT, lng=BASIN_CENTER_LNG),
                    watershed_id="basin_default",
                    bbox=basin_bbox,
                    confidence=0.9,  # independent system confirmation
                    agreeing_sensors=1,
                    total_sensors=1,
                    source_readings=[],
                    timestamp=datetime.utcnow(),
                )
                await self.event_bus.emit("anomaly_alerts", alert.model_dump())
                self.log_action(
                    "emit_gdacs_confirmation",
                    f"GDACS {event['alert_level'].upper()} flood event "
                    f"'{event.get('name', '?')}' overlaps basin bbox — "
                    "independent confirmation boost",
                    0.9,
                    data_sources=["GDACS:continuous"],
                )

    # ── Anomaly detection ────────────────────────────────────────────

    def _detect_anomaly(self, reading: SensorReading) -> AnomalyAlert | None:
        """Compute z-score against baseline and create alert if significant.

        Algorithm:
            1. Look up baseline for (watershed_id, metric)
            2. z = (value - mean) / std
            3. Classify severity by threshold:  LOW(1.5σ), MEDIUM(2.5σ), HIGH(3.5σ), CRITICAL(5σ)
            4. Check multi-sensor agreement:  at least 2 sensors must agree
            5. Confidence = agreeing_sensors / total_sensors

        Returns:
            AnomalyAlert if z-score exceeds LOW threshold and multi-sensor
            agreement is met, else None.
        """
        key = (reading.watershed_id, reading.metric)
        baseline = self._baselines.get(key)

        if baseline is None:
            # No baseline yet — create one from this reading (cold start)
            self._baselines[key] = Baseline(
                watershed_id=reading.watershed_id,
                metric=reading.metric,
                window_days=30,
                mean=reading.value,
                std=max(abs(reading.value) * 0.1, 0.1),  # Initial estimate
                sample_count=1,
            )
            return None

        # Compute z-score
        z_score = abs(reading.value - baseline.mean) / baseline.std

        # Classify severity
        level: AlertLevel | None = None
        if z_score >= ANOMALY_THRESHOLDS["CRITICAL"]:
            level = AlertLevel.CRITICAL
        elif z_score >= ANOMALY_THRESHOLDS["HIGH"]:
            level = AlertLevel.HIGH
        elif z_score >= ANOMALY_THRESHOLDS["MEDIUM"]:
            level = AlertLevel.MEDIUM
        elif z_score >= ANOMALY_THRESHOLDS["LOW"]:
            level = AlertLevel.LOW

        if level is None:
            # Update baseline with exponential moving average
            self._update_baseline(baseline, reading.value)
            return None

        # Multi-sensor agreement check
        recent_same_metric = [
            r for r in self._recent_readings
            if r.watershed_id == reading.watershed_id
            and r.metric == reading.metric
            and r.sensor_id != reading.sensor_id
            and abs((r.timestamp - reading.timestamp).total_seconds()) < 1800  # 30 min window
        ]
        agreeing = sum(
            1 for r in recent_same_metric
            if abs(r.value - baseline.mean) / baseline.std >= ANOMALY_THRESHOLDS["LOW"]
        )
        total_sensors = len(recent_same_metric) + 1
        agreeing_sensors = agreeing + 1  # Include current reading

        if agreeing_sensors < 2 and total_sensors >= 2:
            # Not enough sensor agreement — suppress false positive
            self._logger.debug(
                "Anomaly suppressed: only %d/%d sensors agree for %s",
                agreeing_sensors, total_sensors, reading.sensor_id,
            )
            return None

        confidence = agreeing_sensors / max(total_sensors, 1)

        return AnomalyAlert(
            alert_id=str(uuid.uuid4()),
            level=level,
            metric=reading.metric,
            value=reading.value,
            deviation_sigma=round(z_score, 2),
            location=reading.location,
            watershed_id=reading.watershed_id,
            bbox=BBox(
                south=reading.location.lat - 0.1,
                west=reading.location.lng - 0.1,
                north=reading.location.lat + 0.1,
                east=reading.location.lng + 0.1,
            ),
            confidence=round(confidence, 2),
            agreeing_sensors=agreeing_sensors,
            total_sensors=total_sensors,
            source_readings=[reading],
            timestamp=datetime.utcnow(),
        )

    def _update_baseline(self, baseline: Baseline, new_value: float) -> None:
        """Update baseline with exponential weighted moving average.

        Uses Welford's online algorithm for numerically stable
        running mean and variance updates.
        """
        n = baseline.sample_count + 1
        delta = new_value - baseline.mean
        new_mean = baseline.mean + delta / n
        delta2 = new_value - new_mean
        # Running variance (Welford)
        new_var = ((baseline.std ** 2) * (baseline.sample_count - 1) + delta * delta2) / max(n - 1, 1)
        baseline.mean = new_mean
        baseline.std = max(new_var ** 0.5, 0.01)  # Floor to prevent division by zero
        baseline.sample_count = min(n, 10000)  # Cap to prevent overflow
        baseline.last_updated = datetime.utcnow()

    # ── Recession detection ──────────────────────────────────────────

    async def _check_recession(self) -> None:
        """Detect flood recession by checking gauge level trends.

        If a gauge shows 4+ consecutive hours of declining levels after
        a flood peak, emit a FloodRecedingEvent to trigger DiseaseRiskAgent.
        """
        for gauge_id, history in self._gauge_history.items():
            if len(history) < DEESCALATION_GAUGE_HOURS * 4:  # 4 readings/hour min
                continue

            # Get last N hours of readings
            cutoff = datetime.utcnow() - timedelta(hours=DEESCALATION_GAUGE_HOURS)
            recent = [(t, v) for t, v in history if t > cutoff]
            if len(recent) < 4:
                continue

            # Check monotonically decreasing
            values = [v for _, v in sorted(recent)]
            is_receding = all(values[i] >= values[i + 1] for i in range(len(values) - 1))

            if is_receding and values[0] > values[-1] * 1.05:  # At least 5% drop
                peak_val = max(v for _, v in history)
                peak_time = next(t for t, v in history if v == peak_val)

                event = FloodRecedingEvent(
                    event_id=str(uuid.uuid4()),
                    zone_id=f"zone_{gauge_id}",
                    bbox=BBox(south=0, west=0, north=1, east=1),  # Stub bbox
                    peak_water_level_m=peak_val,
                    peak_timestamp=peak_time,
                    recession_start=recent[0][0],
                    flood_duration_hours=float(
                        (recent[0][0] - peak_time).total_seconds() / 3600
                    ),
                    flood_depth_max_m=peak_val,
                    timestamp=datetime.utcnow(),
                )
                await self.event_bus.emit("flood_receding", event.model_dump())
                self._logger.info(
                    "Flood receding detected at gauge %s: peak=%.2fm, current=%.2fm",
                    gauge_id, peak_val, values[-1],
                )
                # Clear history after emitting to prevent duplicate events
                self._gauge_history[gauge_id] = recent[-4:]

    # ── Stub data generation ─────────────────────────────────────────

    def _generate_stub_readings(
        self, metric: str, source: DataSource
    ) -> list[SensorReading]:
        """Generate realistic stub sensor readings.

        STUB: Returns synthetic data for development/testing.
        In production, replaced by connector calls.
        """
        return [
            SensorReading(
                sensor_id=f"STUB-{source.value}-001",
                source=source,
                metric=metric,
                value=25.0 if metric == "rainfall_mm" else 2.5,
                unit="mm" if metric == "rainfall_mm" else "m",
                location=Coordinate(lat=38.9, lng=-77.0),
                watershed_id="HB-020700",
                timestamp=datetime.utcnow(),
            ),
        ]
