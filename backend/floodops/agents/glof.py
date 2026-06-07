"""
GLOFAgent — Glacial Lake Outburst Flood monitor.

GLOFAgent assesses dam integrity for glacial lakes and triggers the
emergency bypass path when a breach is imminent. This is the ONLY agent
that uses direct_call() to AlertAgent — bypassing all queues because
moraine dam failures can send a wall of water downstream in <30 minutes.

Triggers: CRON (every 6 days — matches Sentinel-1 revisit) + HTTP_DIRECT
Emits:    "glof_reports"    → normal queue for routine lake health
          direct_call("alert_agent") → GLOF emergency bypass
          "glof_emergencies" → recorded in state for audit trail

Data flow::

    GLIMS inventory ──┐
    Sentinel SAR    ──┼──► GLOFAgent ──integrity < 0.3──► direct_call AlertAgent
    HydroSHEDS DEM  ──┘            └──integrity >= 0.3──► glof_reports queue
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from floodops.agents.base import BaseAgent
from floodops.config import CRON_GLOF_LAKES, GLOF_BREACH_THRESHOLD, GLOF_VOLUME_ALERT_FACTOR
from floodops.models.enums import FloodPhase, TriggerType
from floodops.models.geo import BBox, Coordinate, GeoJsonGeometry
from floodops.models.glof import GLOFEmergency, ImpactZone, LakeHealthReport, VolumeEstimate
from floodops.queue.event_bus import EventBus

logger = logging.getLogger(__name__)


class GLOFAgent(BaseAgent):
    """Monitors glacial lakes and triggers emergency bypass on dam breach.

    Internal state:
        _lake_inventory: Static lake catalog from GLIMS.
        _previous_reports: Last health report per lake for delta comparison.
    """

    agent_id: str = "glof_agent"
    trigger_types: set[TriggerType] = {TriggerType.CRON, TriggerType.HTTP_DIRECT}

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__(event_bus)
        self._lake_inventory: list[dict[str, Any]] = []
        self._previous_reports: dict[str, LakeHealthReport] = {}

    async def initialize(self) -> None:
        """Register CRON scan and direct handler for manual assessments."""
        await self.event_bus.register_cron(
            CRON_GLOF_LAKES,
            self._scan_lakes,
            job_id="glof_scan",
        )
        self.event_bus.register_direct_handler(self.agent_id, self.handle_direct)
        self._logger.info("GLOFAgent initialised with CRON + HTTP_DIRECT")

    async def handle_event(self, channel: str, payload: Any) -> None:
        """Handle manual rescan requests."""
        if channel == "glof_rescan":
            await self._scan_lakes()

    async def handle_direct(self, payload: Any) -> dict[str, Any]:
        """Handle direct assessment request for a specific lake.

        Used by the API when a user requests an on-demand lake assessment.
        """
        lake_id = payload.get("lake_id") if isinstance(payload, dict) else getattr(payload, "lake_id", None)
        if lake_id:
            report = await self._assess_lake(lake_id)
            if report is not None:
                return report.model_dump()
        return {"status": "lake_not_found"}

    # ── Core scan logic ──────────────────────────────────────────────

    async def _scan_lakes(self) -> None:
        """Scan all monitored glacial lakes for volume changes and dam integrity.

        STUB: In production, this calls:
          1. GLIMSConnector.get_lake_inventory() for the catalog
          2. SentinelHubConnector.get_sar_imagery(lake.bbox) for surface area
          3. HydroSHEDSConnector.get_dem(lake.bbox) for depth estimation
          4. Computes integrity score from SAR coherence + DEM differencing

        The integrity scoring pipeline:
          - Moraine dams: DEM change detection reveals erosion/piping
          - Ice dams: SAR coherence loss indicates thinning
          - Volume delta: rapid filling signals increased outburst risk
          - Temperature: above-freezing days accelerate ice dam weakening
        """
        self._logger.info("Starting glacial lake scan cycle")

        # --- STUB: Replace with real connector calls ---
        lake_ids = self._get_stub_lake_inventory()
        # --- END STUB ---

        for lake_info in lake_ids:
            report = await self._assess_lake(lake_info["lake_id"], lake_info=lake_info)
            if report is None:
                continue

            # Store for delta comparison
            self._previous_reports[report.lake_id] = report

            # Route based on integrity score
            if report.integrity_score < GLOF_BREACH_THRESHOLD:
                # EMERGENCY BYPASS — direct call to AlertAgent
                await self._trigger_emergency(report)
            else:
                # Normal queue for routine monitoring
                await self.event_bus.emit("glof_reports", report)
                self.log_action(
                    action="emit_lake_health",
                    reasoning=(
                        f"Lake {report.lake_name or report.lake_id}: integrity={report.integrity_score:.2f}, "
                        f"volume_delta={report.volume.volume_delta_pct:+.1f}%. "
                        f"Dam type: {report.dam_type}. Status: {report.risk_level}."
                    ),
                    confidence=0.8,
                    phase=FloodPhase.MONITORING,
                    output_summary=f"risk_level={report.risk_level}",
                    data_sources=["GLIMS:static", "SENTINEL_SAR:6-12day"],
                )

        self._logger.info("Glacial lake scan complete: %d lakes assessed", len(lake_ids))

    async def _assess_lake(
        self, lake_id: str, lake_info: dict[str, Any] | None = None,
    ) -> LakeHealthReport | None:
        """Assess a single glacial lake.

        STUB: Core assessment logic. In production, this runs the full
        integrity scoring pipeline using SAR data and DEM analysis.
        """
        if lake_info is None:
            lake_info = {"lake_id": lake_id, "name": f"Lake {lake_id}", "lat": 28.0, "lng": 86.0}

        lat = lake_info.get("lat", 28.0)
        lng = lake_info.get("lng", 86.0)

        # --- STUB: Compute volume and integrity ---
        previous = self._previous_reports.get(lake_id)
        prev_volume = previous.volume.current_volume_m3 if previous else 5_000_000.0

        volume = VolumeEstimate(
            lake_id=lake_id,
            surface_area_km2=0.45,
            estimated_depth_m=12.0,
            current_volume_m3=5_200_000.0,
            previous_volume_m3=prev_volume,
            volume_delta_m3=200_000.0,
            volume_delta_pct=4.0,
            measurement_date=datetime.utcnow(),
            source="SAR",
        )

        integrity = self._compute_integrity_score(volume, lake_info)
        risk_level = self._classify_risk(integrity, volume)
        # --- END STUB ---

        return LakeHealthReport(
            lake_id=lake_id,
            lake_name=lake_info.get("name"),
            location=Coordinate(lat=lat, lng=lng),
            bbox=BBox(south=lat - 0.05, west=lng - 0.05, north=lat + 0.05, east=lng + 0.05),
            elevation_m=lake_info.get("elevation", 4500.0),
            dam_type=lake_info.get("dam_type", "moraine"),
            volume=volume,
            integrity_score=integrity,
            risk_level=risk_level,
            scan_date=datetime.utcnow(),
            next_scan_date=datetime.utcnow() + timedelta(days=6),
        )

    def _compute_integrity_score(
        self, volume: VolumeEstimate, lake_info: dict[str, Any],
    ) -> float:
        """Compute dam integrity score [0, 1].

        STUB: In production, combines:
          - SAR coherence change (moraine erosion detection)
          - DEM differencing (dam crest lowering)
          - Volume growth rate (rapid filling = higher pressure)
          - Temperature trend (ice dam weakening)

        Returns value between 0 (failed) and 1 (stable).
        """
        # Base integrity from lake metadata
        base = lake_info.get("base_integrity", 0.85)

        # Penalize rapid volume growth
        if abs(volume.volume_delta_pct) > GLOF_VOLUME_ALERT_FACTOR * 100:
            base -= 0.2

        # Additional factors would come from SAR analysis
        return max(0.0, min(1.0, base))

    def _classify_risk(self, integrity: float, volume: VolumeEstimate) -> str:
        """Classify risk level from integrity score."""
        if integrity < 0.3:
            return "CRITICAL"
        elif integrity < 0.5:
            return "HIGH"
        elif integrity < 0.7:
            return "MEDIUM"
        return "LOW"

    # ── Emergency bypass ─────────────────────────────────────────────

    async def _trigger_emergency(self, report: LakeHealthReport) -> None:
        """Trigger GLOF emergency bypass — direct call to AlertAgent.

        This is the time-critical path. Confirmed GLOF breaches bypass
        all queues and invoke AlertAgent directly. Time-to-impact can
        be <30 minutes for downstream communities.
        """
        self._logger.critical(
            "GLOF EMERGENCY: Lake %s integrity=%.2f — triggering direct bypass!",
            report.lake_id, report.integrity_score,
        )

        impact_zone = ImpactZone(
            lake_id=report.lake_id,
            geometry=GeoJsonGeometry(
                type="Polygon",
                coordinates=[[[
                    report.bbox.west, report.bbox.south,
                ], [
                    report.bbox.east, report.bbox.south,
                ], [
                    report.bbox.east, report.bbox.north,
                ], [
                    report.bbox.west, report.bbox.north,
                ], [
                    report.bbox.west, report.bbox.south,
                ]]],
            ),
            peak_discharge_m3s=report.volume.current_volume_m3 / 3600,
            time_to_impact_minutes=25.0,
            affected_population=5000,
            flood_depth_max_m=3.0,
            confidence=0.75,
        )

        emergency = GLOFEmergency(
            lake_id=report.lake_id,
            lake_name=report.lake_name,
            integrity_score=report.integrity_score,
            impact_zone=impact_zone,
            breach_type="imminent" if report.integrity_score > 0.1 else "confirmed",
            recommended_action="IMMEDIATE_EVACUATION",
            timestamp=datetime.utcnow(),
        )

        # Direct call — bypasses queue
        try:
            await self.event_bus.direct_call("alert_agent", emergency)
        except KeyError:
            self._logger.error("AlertAgent not registered for direct calls!")

        # Also emit to queue for state recording
        await self.event_bus.emit("glof_emergencies", emergency)

        self.log_action(
            action="glof_emergency_bypass",
            reasoning=(
                f"CRITICAL: Lake {report.lake_name or report.lake_id} integrity={report.integrity_score:.2f} "
                f"(threshold={GLOF_BREACH_THRESHOLD}). Volume={report.volume.current_volume_m3:.0f}m³, "
                f"delta={report.volume.volume_delta_pct:+.1f}%. "
                f"Time to impact: {impact_zone.time_to_impact_minutes:.0f}min. "
                f"Affected population: {impact_zone.affected_population}. "
                f"DIRECT BYPASS to AlertAgent — no queue delay."
            ),
            confidence=0.9,
            phase=FloodPhase.EVACUATION,
            output_summary="GLOF_EMERGENCY_BYPASS",
            data_sources=["GLIMS:static", "SENTINEL_SAR:6-12day", "HYDROSHEDS:static"],
        )

    # ── Stub data ────────────────────────────────────────────────────

    def _get_stub_lake_inventory(self) -> list[dict[str, Any]]:
        """Return stub glacial lake inventory.

        STUB: In production, fetched from GLIMSConnector.
        """
        return [
            {
                "lake_id": "GLIMS-GL090210E28245N",
                "name": "Tsho Rolpa",
                "lat": 27.87,
                "lng": 86.48,
                "elevation": 4580,
                "dam_type": "moraine",
                "base_integrity": 0.72,
            },
            {
                "lake_id": "GLIMS-GL086580E28040N",
                "name": "Imja Lake",
                "lat": 27.90,
                "lng": 86.93,
                "elevation": 5010,
                "dam_type": "moraine",
                "base_integrity": 0.85,
            },
        ]
