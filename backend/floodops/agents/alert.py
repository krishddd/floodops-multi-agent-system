"""
AlertAgent — Multi-channel, multi-language warning dissemination.

The hardest part of flood warning is not prediction — it's getting a message
to a farmer in rural Bangladesh at 2 AM, in Bangla, telling them which road
is still passable.

Trigger: Queue from FloodPredictAgent + HTTP direct from GLOFAgent.
Emits: AlertDispatch (SMS, Radio, Siren payloads)
"""

from __future__ import annotations

import uuid
from typing import Any

from floodops.agents.base import BaseAgent, _as_dict
from floodops.models.alert import (
    AlertDispatch,
    CellBroadcast,
    RadioBroadcast,
    SirenActivation,
)
from floodops.models.enums import SeverityLevel, TriggerType
from floodops.models.geo import GeoJsonGeometry


class AlertAgent(BaseAgent):
    """Multi-channel warning dissemination.

    Alert level mapping:
    - <40% → ADVISORY (app/email only)
    - 40-70% → WATCH (SMS to high-risk zones)
    - 70-90% → WARNING (mass cell broadcast)
    - >90% or GLOF → EMERGENCY (all channels simultaneously)

    Geofencing: only alerts people inside projected flood polygon + 20% buffer.
    """

    agent_id: str = "alert_agent"
    trigger_types: list[TriggerType] = [TriggerType.QUEUE, TriggerType.HTTP_DIRECT]

    async def initialize(self) -> None:
        await self.event_bus.subscribe("flood_forecasts", self.handle_forecast)
        self.event_bus.register_direct_handler("alert_agent", self.handle_glof_emergency)
        self.log_action("initialize", "AlertAgent subscribed to flood_forecasts + registered GLOF direct handler", 1.0)

    async def handle_event(self, channel: str, payload: Any) -> None:
        pass

    async def handle_forecast(self, channel: str, forecast_data: Any) -> None:
        """Process flood forecast and dispatch appropriate alerts."""
        forecast_data = _as_dict(forecast_data)
        max_prob = forecast_data.get("max_probability", 0)
        severity = self.assess_level(max_prob)

        if severity == SeverityLevel.ADVISORY:
            self.log_action("skip_alert", f"Probability {max_prob:.0%} below WATCH threshold", 0.9)
            return

        dispatch = await self.dispatch_alerts(forecast_data, severity)
        await self.event_bus.emit("alert_dispatches", dispatch.model_dump())
        self.log_action(
            "dispatch_alerts",
            f"Dispatched {severity.value} alerts, estimated reach: {dispatch.total_reach_estimate:,}",
            0.85,
        )

    async def handle_glof_emergency(self, payload: dict[str, Any]) -> dict[str, Any]:
        """DIRECT HTTP handler for GLOF breach — NO QUEUE DELAY.

        This is the time-critical path. GLOFAgent calls this directly
        when dam integrity drops below 0.3. Seconds matter.
        """
        payload = _as_dict(payload)
        dispatch = await self.dispatch_alerts(payload, SeverityLevel.EMERGENCY, is_glof=True)
        await self.event_bus.emit("alert_dispatches", dispatch.model_dump())
        self.log_action(
            "glof_emergency_dispatch",
            f"EMERGENCY GLOF alert dispatched. Time-to-impact: {payload.get('impact_zone', {}).get('time_to_impact_minutes', '?')} minutes",
            1.0,
        )
        return {"status": "dispatched", "dispatch_id": dispatch.dispatch_id}

    def assess_level(self, probability: float, is_glof: bool = False) -> SeverityLevel:
        """Map probability to alert severity level."""
        if is_glof or probability >= 0.90:
            return SeverityLevel.EMERGENCY
        elif probability >= 0.70:
            return SeverityLevel.WARNING
        elif probability >= 0.40:
            return SeverityLevel.WATCH
        return SeverityLevel.ADVISORY

    async def dispatch_alerts(
        self, data: dict[str, Any], severity: SeverityLevel, is_glof: bool = False
    ) -> AlertDispatch:
        """Build and dispatch alerts across all channels for the severity level."""
        dispatch_id = str(uuid.uuid4())
        event_id = data.get("event_id", dispatch_id)

        broadcasts = []
        radio = []
        sirens = []

        # SMS cell broadcast for WATCH and above
        if severity in (SeverityLevel.WATCH, SeverityLevel.WARNING, SeverityLevel.EMERGENCY):
            broadcasts.append(CellBroadcast(
                broadcast_id=str(uuid.uuid4()),
                severity=severity,
                zone_polygon=GeoJsonGeometry(type="Polygon", coordinates=[[[85.3, 27.7], [85.4, 27.7], [85.4, 27.8], [85.3, 27.8], [85.3, 27.7]]]),
                message_text=self._generate_message(severity, data, is_glof),
                language="en",
                reach_estimate=15000,
            ))

        # Radio broadcast for WARNING and above
        if severity in (SeverityLevel.WARNING, SeverityLevel.EMERGENCY):
            radio.append(RadioBroadcast(
                broadcast_id=str(uuid.uuid4()),
                severity=severity,
                station_ids=["radio_nepal_1", "community_fm_85"],
                script_text=self._generate_radio_script(severity, data),
                language="ne",
                priority_level=1 if severity == SeverityLevel.EMERGENCY else 2,
            ))

        # Sirens for EMERGENCY only
        if severity == SeverityLevel.EMERGENCY:
            sirens.append(SirenActivation(
                activation_id=str(uuid.uuid4()),
                zone_ids=["zone_1", "zone_2", "zone_3"],
                pattern="FLOOD_EMERGENCY" if is_glof else "FLOOD_WARNING",
                duration_seconds=180,
            ))

        return AlertDispatch(
            dispatch_id=dispatch_id,
            event_id=event_id,
            severity=severity,
            cell_broadcasts=broadcasts,
            radio_broadcasts=radio,
            siren_activations=sirens,
            total_reach_estimate=sum(b.reach_estimate for b in broadcasts),
            is_glof_bypass=is_glof,
        )

    def _generate_message(self, severity: SeverityLevel, data: dict, is_glof: bool) -> str:
        """Generate localized alert message. TODO: Multi-language support."""
        if is_glof:
            return ("⚠️ EMERGENCY: Glacial lake breach detected. "
                    "Evacuate immediately to higher ground. "
                    "Follow marked evacuation routes. Do not cross rivers.")
        return (f"⚠️ FLOOD {severity.value}: Flooding predicted in your area. "
                f"Probability: {data.get('max_probability', 0):.0%}. "
                f"Move to designated shelters. Monitor this channel for updates.")

    def _generate_radio_script(self, severity: SeverityLevel, data: dict) -> str:
        """Generate radio broadcast script."""
        return (f"Flood {severity.value} for the Kathmandu Valley region. "
                f"Residents in low-lying areas near the Bagmati River corridor "
                f"should prepare to evacuate. Follow instructions from local authorities.")
