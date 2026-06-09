"""
CompoundEventAgent — multi-hazard co-occurrence detector and synthesizer.

Most disaster systems treat hazards independently. The CompoundEventAgent
watches the hazard signals from the other agents and detects when multiple
hazards co-occur in the same spatial/temporal window — flood + GLOF surge +
landslide + disease — then fuses them into a single, explainable unified
threat score for an emergency commander.

Techniques applied (core-3): ensemble voting on the fused score, uncertainty
quantification (epistemic across hazards), and causal attribution of the
compounding mechanisms.

Trigger: QUEUE — subscribes to flood_forecasts, disease_risk,
         glof_emergencies, anomaly_alerts.
Emits:   CompoundThreat → compound_threats
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from floodops.agents.base import BaseAgent, _as_dict
from floodops.config import COMPOUND_WINDOW_HOURS
from floodops.llm.prompts import COMPOUND_EVENT_SYSTEM_PROMPT
from floodops.models.compound import CompoundThreat, ContributingHazard
from floodops.models.enums import TriggerType
from floodops.models.geo import BBox, GeoJsonGeometry
from floodops.models.reasoning import ReasonedAssessment

# How long a hazard signal stays "active" for co-occurrence correlation (config).
_CORRELATION_WINDOW = timedelta(hours=COMPOUND_WINDOW_HOURS)
# Minimum distinct hazards required to declare a compound event.
_MIN_HAZARDS = 2
# Re-emit only when the unified score moves more than this since the last emission.
_SCORE_DELTA = 0.1


class CompoundEventAgent(BaseAgent):
    """Detects co-occurring hazards and synthesizes a unified threat score."""

    agent_id: str = "compound_event_agent"
    trigger_types: set[TriggerType] = {TriggerType.QUEUE}

    def __init__(self, event_bus, llm=None) -> None:
        super().__init__(event_bus, llm)
        # Recent hazard signals: hazard_type -> (timestamp, ContributingHazard, bbox)
        self._active: dict[str, tuple[datetime, ContributingHazard, BBox]] = {}
        self._last_event_id: str = ""
        # Dedup state: last emitted (hazard-type set, unified score).
        self._last_emit_key: frozenset[str] = frozenset()
        self._last_emit_score: float = -1.0

    async def initialize(self) -> None:
        await self.event_bus.subscribe("flood_forecasts", self.handle_signal)
        await self.event_bus.subscribe("disease_risk", self.handle_signal)
        await self.event_bus.subscribe("glof_emergencies", self.handle_signal)
        await self.event_bus.subscribe("anomaly_alerts", self.handle_signal)
        self.log_action(
            "initialize",
            "CompoundEventAgent subscribed to flood/disease/glof/anomaly channels",
            1.0,
        )

    async def handle_event(self, channel: str, payload: Any) -> None:  # pragma: no cover
        await self.handle_signal(channel, payload)

    async def handle_signal(self, channel: str, payload: Any) -> None:
        """Record a hazard signal and re-evaluate compound risk."""
        data = _as_dict(payload)
        hazard, bbox = self._classify(channel, data)
        if hazard is None or bbox is None:
            return

        now = datetime.utcnow()
        self._active[hazard.hazard_type] = (now, hazard, bbox)
        self._last_event_id = data.get("event_id") or data.get("alert_id") or self._last_event_id

        # Prune stale signals outside the correlation window.
        self._active = {
            k: v for k, v in self._active.items() if now - v[0] <= _CORRELATION_WINDOW
        }

        if len(self._active) >= _MIN_HAZARDS:
            threat = await self._synthesize()
            if threat is None:
                return
            # Dedup / anti-flood (#A): emit only when the active hazard-type set
            # changes OR the unified score moved materially since last emission.
            # Keyed on the hazard-type SET (not event_id, which is per-signal).
            key = frozenset(h.hazard_type for h in threat.contributing_hazards)
            score = threat.unified_threat_score
            if key == self._last_emit_key and abs(score - self._last_emit_score) <= _SCORE_DELTA:
                return
            self._last_emit_key = key
            self._last_emit_score = score
            await self.event_bus.emit("compound_threats", threat.model_dump())
            self.log_action(
                "emit_compound_threat",
                f"{len(threat.contributing_hazards)} co-occurring hazards -> "
                f"unified threat {threat.unified_threat_score:.0%}. {threat.summary}",
                threat.confidence,
            )

    # ── Classification ───────────────────────────────────────────────

    def _classify(
        self, channel: str, data: dict[str, Any]
    ) -> tuple[ContributingHazard | None, BBox | None]:
        """Map an incoming event to a (ContributingHazard, BBox)."""
        bbox = self._extract_bbox(data)
        if channel == "flood_forecasts":
            sev = float(data.get("max_probability", 0.0) or 0.0)
            return (
                ContributingHazard(
                    hazard_type="flood", source_agent="flood_predict_agent",
                    severity=sev,
                    detail=f"flood probability {sev:.0%}",
                ),
                bbox,
            )
        if channel == "glof_emergencies":
            integrity = float(data.get("integrity_score", 1.0) or 1.0)
            sev = max(0.0, min(1.0, 1.0 - integrity))
            return (
                ContributingHazard(
                    hazard_type="glof", source_agent="glof_agent", severity=sev,
                    detail=f"dam integrity {integrity:.2f}",
                ),
                bbox,
            )
        if channel == "disease_risk":
            hotspots = data.get("hotspots", []) or []
            sev = max((float(h.get("risk_score", 0.0) or 0.0) for h in hotspots), default=0.0)
            return (
                ContributingHazard(
                    hazard_type="disease", source_agent="disease_risk_agent",
                    severity=sev, detail=f"peak pathogen risk {sev:.0%}",
                ),
                bbox,
            )
        if channel == "anomaly_alerts":
            sigma = float(data.get("deviation_sigma", 0.0) or 0.0)
            sev = max(0.0, min(1.0, sigma / 5.0))
            # Treat strong gauge/soil anomalies as a landslide proxy signal.
            return (
                ContributingHazard(
                    hazard_type="landslide", source_agent="sentinel_agent",
                    severity=sev, detail=f"saturation anomaly {sigma:.1f}σ",
                ),
                bbox,
            )
        return None, None

    def _extract_bbox(self, data: dict[str, Any]) -> BBox | None:
        bbox = data.get("bbox")
        if isinstance(bbox, dict):
            try:
                return BBox(**bbox)
            except Exception:
                return None
        # GLOF emergencies nest geometry under impact_zone; fall back to a default.
        loc = data.get("location")
        if isinstance(loc, dict) and "lat" in loc and "lng" in loc:
            lat, lng = loc["lat"], loc["lng"]
            return BBox(south=lat - 0.1, west=lng - 0.1, north=lat + 0.1, east=lng + 0.1)
        return None

    # ── Synthesis ────────────────────────────────────────────────────

    async def _synthesize(self) -> CompoundThreat | None:
        # Spatial correlation (#4): only hazards whose bbox overlaps at least one
        # other active hazard's bbox can compound; isolated hazards don't.
        active = list(self._active.values())
        if len(active) < _MIN_HAZARDS:
            return None
        kept = [
            (h, b) for (_, h, b) in active
            if any(self._bbox_overlap(b, ob) for (_, oh, ob) in active if oh is not h)
        ]
        if len(kept) < _MIN_HAZARDS:
            return None
        hazards = [h for (h, _) in kept]
        bboxes = [b for (_, b) in kept]

        severities = [h.severity for h in hazards]
        # Deterministic pre-LLM fusion (#5): base = max single-hazard severity,
        # amplified by co-occurrence; amplification is capped so base*amp <= 1.0.
        base = max(severities)
        amplification = min(1.0 / base if base > 0 else 1.0,
                            1.0 + 0.15 * (len(hazards) - 1))
        det_score = round(min(1.0, base * amplification), 3)
        bounds = self._quantify_uncertainty(severities, ensemble_spread=severities)
        region = self._merge_bboxes(bboxes)
        hotspot = GeoJsonGeometry(
            type="Point",
            coordinates=[region.center().lng, region.center().lat],
        )

        compounding = self._compounding_factors(hazards)
        det_summary = (
            f"{len(hazards)} co-occurring hazards ("
            + ", ".join(f"{h.hazard_type} {h.severity:.0%}" for h in hazards)
            + f"); compounded threat {det_score:.0%}."
        )

        mock = ReasonedAssessment(
            agent_id=self.agent_id,
            value=det_score,
            confidence=max(0.1, bounds.confidence),
            summary=det_summary,
            causal_factors=compounding,
            competing_hypothesis="Hazards may resolve independently without compounding.",
        )
        assessment = await self._ensemble_vote(
            system=COMPOUND_EVENT_SYSTEM_PROMPT,
            data={
                "hazards": [h.model_dump() for h in hazards],
                "deterministic_score": det_score,
            },
            context=None,
            schema=ReasonedAssessment,
            mock=mock,
        )

        # Deterministic fused score drives the threat number (safety); the LLM
        # enriches the explanation and confidence.
        return CompoundThreat(
            threat_id=str(uuid.uuid4()),
            event_id=self._last_event_id or str(uuid.uuid4()),
            region=region,
            hotspot=hotspot,
            unified_threat_score=det_score,
            confidence=assessment.confidence,
            uncertainty=bounds,
            contributing_hazards=hazards,
            compounding_factors=assessment.causal_factors or compounding,
            recommended_action=self._recommend(det_score, hazards),
            summary=assessment.summary,
        )

    @staticmethod
    def _compounding_factors(hazards: list[ContributingHazard]) -> list[str]:
        types = {h.hazard_type for h in hazards}
        factors: list[str] = []
        if "flood" in types and "landslide" in types:
            factors.append("Flood saturation destabilizes slopes → landslide risk")
        if "flood" in types and "disease" in types:
            factors.append("Standing flood water → waterborne disease vector")
        if "glof" in types and "flood" in types:
            factors.append("GLOF surge superimposed on riverine flood peak")
        if not factors:
            factors.append("Concurrent hazards strain the same response capacity")
        return factors

    @staticmethod
    def _bbox_overlap(a: BBox, b: BBox) -> bool:
        """True if two bounding boxes intersect (any shared area)."""
        return not (a.east < b.west or b.east < a.west
                    or a.north < b.south or b.north < a.south)

    @staticmethod
    def _merge_bboxes(bboxes: list[BBox]) -> BBox:
        return BBox(
            south=min(b.south for b in bboxes),
            west=min(b.west for b in bboxes),
            north=max(b.north for b in bboxes),
            east=max(b.east for b in bboxes),
        )

    @staticmethod
    def _recommend(score: float, hazards: list[ContributingHazard]) -> str:
        if score >= 0.8:
            return "UNIFIED EMERGENCY COMMAND: evacuate overlap zone, stage multi-hazard response."
        if score >= 0.5:
            return "Elevate to joint response; pre-stage assets for the dominant hazard."
        return "Monitor compounding hazards; maintain readiness."
