"""
FloodReasoner — High-level reasoning API for agents and API routes.

Wraps FloodLLMClient with domain-specific methods that agents and
API endpoints call. Handles data marshaling between Pydantic models
and prompt templates.
"""

from __future__ import annotations

from typing import Any, Optional

from floodops.llm.client import FloodLLMClient
from floodops.models.orchestrator import DataSourceBadge, WhyCardData


class FloodReasoner:
    """Domain-specific reasoning layer for FloodOps."""

    def __init__(self, llm_client: Optional[FloodLLMClient] = None):
        self.llm = llm_client or FloodLLMClient()

    async def generate_why_card(self, feature_data: dict[str, Any]) -> WhyCardData:
        """Generate a spatial 'why' card for a map feature.

        Called by: GET /api/v1/flood/reasoning?zone_id=X
        Rendered by: frontend/src/reasoning/why-cards.js
        """
        llm_result = await self.llm.generate_why_card(feature_data)

        return WhyCardData(
            feature_id=feature_data.get("zone_id", feature_data.get("feature_id", "unknown")),
            feature_type=feature_data.get("feature_type", "zone"),
            feature_name=feature_data.get("zone_name", feature_data.get("feature_name", "Unknown")),
            explanation=llm_result.get("explanation", "Reasoning unavailable"),
            confidence=llm_result.get("confidence", 0.5),
            confidence_explanation=f"Based on {feature_data.get('n_members_flood', '?')}/{feature_data.get('total_members', '?')} ensemble members agreeing",
            majority_view=llm_result.get("majority_view"),
            majority_pct=feature_data.get("n_members_flood", 38) / feature_data.get("total_members", 50) if feature_data.get("total_members") else None,
            minority_view=llm_result.get("minority_view"),
            minority_pct=1.0 - (feature_data.get("n_members_flood", 38) / feature_data.get("total_members", 50)) if feature_data.get("total_members") else None,
            data_sources=[
                DataSourceBadge(source_name="USGS Gauge", last_reading_ago=f"{feature_data.get('minutes_ago', '?')} min ago", freshness_emoji="🟢", cadence="15 min"),
                DataSourceBadge(source_name="ECMWF Ensemble", last_reading_ago="2h ago", freshness_emoji="🟢", cadence="6 hours"),
                DataSourceBadge(source_name="Soil Moisture", last_reading_ago=feature_data.get("soil_age", "14h ago"), freshness_emoji="🟡", cadence="daily"),
            ],
            metrics={
                "population": feature_data.get("population", 0),
                "predicted_depth_m": feature_data.get("predicted_depth_m", 0),
                "drainage_gap_mm": feature_data.get("drainage_gap_mm", 0),
            },
        )

    async def justify_transition(self, from_phase: str, to_phase: str, trigger_data: dict, gate_conditions: dict) -> str:
        """Generate transition justification for audit log."""
        return await self.llm.justify_transition(from_phase, to_phase, trigger_data, gate_conditions)

    async def generate_sitrep(self, state: dict[str, Any]) -> str:
        """Generate situation report."""
        return await self.llm.generate_sitrep(state)
