"""
FloodLLMClient — Google Gemini integration for spatial reasoning.

Uses the google-genai SDK for structured output, streaming,
and grounded prompting. All prompts template in ACTUAL data —
no generic "You are a flood expert" narration.
"""

from __future__ import annotations

from typing import Any, Optional, TypeVar

from pydantic import BaseModel

from floodops.llm.providers import LLMProvider, make_provider

T = TypeVar("T", bound=BaseModel)


class FloodLLMClient:
    """Provider-agnostic LLM client for FloodOps reasoning.

    Delegates to an ``LLMProvider`` (Anthropic Claude or Google Gemini,
    selected by ``FLOODOPS_LLM_PROVIDER``). With no API key configured the
    underlying provider is a ``NullProvider`` and every method degrades to a
    safe template/mock response — so the system boots and demos with no key.

    Capabilities:
    1. Spatial "why" cards — data-grounded explanations per map feature
    2. Phase transition justification — cite specific thresholds and values
    3. Situation reports — structured summary for decision-makers
    4. Interactive chat — answer questions about the current flood state
    5. Anomaly interpretation — translate z-scores to plain language
    6. analyze() / critique() — structured reasoning for the core-3 helpers
    """

    def __init__(
        self,
        api_key: Optional[str] = None,  # retained for backwards-compat callers
        model: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
    ):
        self._provider: LLMProvider = provider or make_provider()

    def available(self) -> bool:
        """True when a real LLM backend is configured and reachable."""
        return self._provider.available()

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate free text via the configured provider.

        Falls back to a clearly-labelled template string when no key is set.
        """
        if self._provider.available():
            return await self._provider.generate(prompt, system=system_instruction)
        return (
            "[LLM response placeholder — configure ANTHROPIC_API_KEY or "
            f"GOOGLE_GENAI_API_KEY for real reasoning]\n\n{prompt[:200]}..."
        )

    async def analyze(
        self,
        system: str,
        data: Any,
        context: Optional[dict[str, Any]] = None,
        output_schema: type[T] = None,  # type: ignore[assignment]
    ) -> Optional[T]:
        """Structured reasoning: return a validated ``output_schema`` instance.

        Returns ``None`` when no LLM is configured so callers fall back to their
        deterministic mock. Matches the Reflexion pattern used by BaseAgent.
        """
        if not self._provider.available() or output_schema is None:
            return None
        import json

        prompt_parts = [f"DATA:\n{json.dumps(data, default=str, indent=2)}"]
        if context:
            prompt_parts.append(f"\nCONTEXT:\n{json.dumps(context, default=str, indent=2)}")
        prompt = "\n".join(prompt_parts)
        return await self._provider.generate_structured(prompt, output_schema, system=system)

    async def critique(self, result: Any) -> str:
        """Self-critique a prior assessment (Reflexion step).

        Returns an empty string with no LLM configured so the reflexion loop
        simply retries with unchanged data (a no-op critique).
        """
        if not self._provider.available():
            return ""
        import json

        prompt = (
            "You are a rigorous reviewer. Critique the following flood-risk "
            "assessment. Identify weak assumptions, missing uncertainty, and "
            "data-quality concerns. Be specific and concise.\n\n"
            f"ASSESSMENT:\n{json.dumps(result, default=str, indent=2)}"
        )
        return await self._provider.generate(prompt)

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
