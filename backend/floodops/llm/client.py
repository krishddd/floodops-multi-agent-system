"""
FloodLLMClient — Google Gemini integration for spatial reasoning.

Uses the google-genai SDK for structured output, streaming,
and grounded prompting. All prompts template in ACTUAL data —
no generic "You are a flood expert" narration.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from floodops.config import GOOGLE_GENAI_API_KEY


class FloodLLMClient:
    """Google Gemini client for FloodOps reasoning.

    Capabilities:
    1. Spatial "why" cards — data-grounded explanations per map feature
    2. Phase transition justification — cite specific thresholds and values
    3. Situation reports — structured summary for decision-makers
    4. Interactive chat — answer questions about the current flood state
    5. Anomaly interpretation — translate z-scores to plain language
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self._api_key = api_key or GOOGLE_GENAI_API_KEY
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except ImportError:
                self._client = None
        return self._client

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate text using Gemini.

        Falls back to template-based generation if SDK not available or key not set.
        """
        client = self._get_client()
        if client and self._api_key:
            try:
                config = {}
                if system_instruction:
                    config["system_instruction"] = system_instruction

                response = client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=config if config else None,
                )
                return response.text or ""
            except Exception as e:
                return f"[LLM unavailable: {e}] Falling back to template response."

        # Fallback — return a structured template response
        return f"[LLM response placeholder — configure GOOGLE_GENAI_API_KEY for real reasoning]\n\n{prompt[:200]}..."

    async def generate_why_card(self, feature_data: dict[str, Any]) -> dict[str, Any]:
        """Generate spatial 'why' card content for a map feature."""
        from floodops.llm.prompts import SPATIAL_REASONING

        prompt = SPATIAL_REASONING.format(**{
            "zone_id": feature_data.get("zone_id", "unknown"),
            "zone_name": feature_data.get("zone_name", "Unknown Zone"),
            "gauge_id": feature_data.get("gauge_id", "N/A"),
            "gauge_value": feature_data.get("gauge_value", "N/A"),
            "z_score": feature_data.get("z_score", "N/A"),
            "minutes_ago": feature_data.get("minutes_ago", "N/A"),
            "soil_pct": feature_data.get("soil_pct", "N/A"),
            "soil_source": feature_data.get("soil_source", "CDS/mock"),
            "soil_age": feature_data.get("soil_age", "N/A"),
            "n_members_flood": feature_data.get("n_members_flood", 38),
            "total_members": feature_data.get("total_members", 50),
            "depth_threshold": feature_data.get("depth_threshold", 0.5),
            "current_phase": feature_data.get("current_phase", "01_ELEVATED"),
            "phase_duration": feature_data.get("phase_duration", "2h"),
        })

        explanation = await self.generate(prompt)

        return {
            "explanation": explanation,
            "confidence": feature_data.get("confidence", 0.75),
            "majority_view": f"{feature_data.get('n_members_flood', 38)} of {feature_data.get('total_members', 50)} members predict significant flooding",
            "minority_view": f"Remaining members predict minor impact if rainfall shifts",
        }

    async def justify_transition(self, from_phase: str, to_phase: str, trigger_data: dict, gate_conditions: dict) -> str:
        """Generate LLM justification for a phase transition."""
        from floodops.llm.prompts import TRANSITION_JUSTIFICATION
        import json

        prompt = TRANSITION_JUSTIFICATION.format(
            from_phase=from_phase,
            to_phase=to_phase,
            trigger_data_json=json.dumps(trigger_data, indent=2, default=str),
            gate_conditions_json=json.dumps(gate_conditions, indent=2),
        )
        return await self.generate(prompt)

    async def generate_sitrep(self, state: dict[str, Any]) -> str:
        """Generate situation report for decision-makers."""
        from floodops.llm.prompts import SITREP

        prompt = SITREP.format(
            current_phase=state.get("current_phase", "unknown"),
            n_alerts=len(state.get("active_alerts", [])),
            n_forecasts=len(state.get("flood_forecasts", [])),
            max_prob=state.get("flood_forecasts", [{}])[-1].get("max_probability", 0) if state.get("flood_forecasts") else 0,
            pop_at_risk=sum(r.get("total_population_at_risk", 0) for r in state.get("urban_risk_reports", [])),
        )
        return await self.generate(prompt)

    async def chat(self, user_message: str, state_context: dict[str, Any]) -> str:
        """Interactive chat about the current flood state."""
        context = (
            f"Current phase: {state_context.get('current_phase', 'unknown')}. "
            f"Active alerts: {len(state_context.get('active_alerts', []))}. "
            f"Latest forecast probability: {state_context.get('max_probability', 'N/A')}."
        )
        prompt = f"CONTEXT:\n{context}\n\nUSER QUESTION:\n{user_message}"

        system = (
            "You are a flood emergency management assistant. Answer based ONLY on the "
            "provided context data. If the data doesn't cover the question, say so. "
            "Always cite specific numbers and data sources."
        )
        return await self.generate(prompt, system_instruction=system)
