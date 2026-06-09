# FloodOps — Engineering Guide (CLAUDE.md)

Production-grade multi-agent flood monitoring, prediction, and disaster-response
platform. Event-driven agents over a 7-phase LangGraph orchestrator, surfaced on
a real-time deck.gl + Google Maps frontend with an LLM chat panel.

**Stack:** Python 3.12 · FastAPI · LangGraph · Pydantic v2 · provider-agnostic LLM
(Anthropic `claude-opus-4-8` or Gemini) · Vite + deck.gl + Google Maps JS (frontend).

---

## Run it

The system boots and demos **with no API key** (deterministic mock fallbacks).

```bash
# Backend
cd backend
pip install -r requirements.txt          # fastapi, langgraph, pydantic, uvicorn, anthropic/google-genai (optional)
uvicorn floodops.api.app:create_app --factory --reload --port 8000

# Frontend
cd frontend
npm install && npm run dev               # http://localhost:5173

# Tests (fully offline)
cd backend && python -m pytest tests -q
```

Add an LLM later by setting `ANTHROPIC_API_KEY` (or `GOOGLE_GENAI_API_KEY`) and
`FLOODOPS_LLM_PROVIDER=anthropic|gemini|auto` in `.env` (see `.env.example`).
With no key, `FloodLLMClient.available()` is `False` and all reasoning helpers
return their deterministic mock values.

Trigger the full pipeline for a demo: `POST /api/v1/flood/simulate`.

---

## The 8 Agents

All inherit `BaseAgent` (`backend/floodops/agents/base.py`), communicate via the
in-memory `EventBus` (`floodops/queue/event_bus.py`), and emit dict payloads
(`.model_dump()`). Event handlers take **`(self, channel, payload)`** — the bus
delivers `handler(channel, payload)`.

| Agent | File | Trigger | Consumes | Emits | Reasoning |
|---|---|---|---|---|---|
| **SentinelAgent** | `agents/sentinel.py` | CRON 15min | NOAA/USGS | `anomaly_alerts`, `flood_receding` | z-score anomaly detection (deterministic) |
| **GLOFAgent** | `agents/glof.py` | CRON 6d + HTTP_DIRECT | GLIMS/SAR | `glof_reports`, `glof_emergencies`, direct→alert | dam integrity (deterministic; <100ms bypass) |
| **FloodPredictAgent** | `agents/predict.py` | `anomaly_alerts` | ECMWF ensemble | `flood_forecasts` | **ensemble-vote** + **uncertainty bounds** |
| **UrbanRiskAgent** | `agents/urban.py` | `flood_forecasts` | OSM/WorldPop | `urban_risk` | **reflexion** per HIGH/CRITICAL zone |
| **AlertAgent** | `agents/alert.py` | `flood_forecasts` + HTTP_DIRECT | — | `alert_dispatches` | severity mapping (deterministic — safety) |
| **ResourceAgent** | `agents/resource.py` | `flood_forecasts`, `disease_risk` | — | `resource_orders` | **reflexion** pre-positioning justification |
| **DiseaseRiskAgent** | `agents/disease.py` | `flood_receding` | WHO/JMP | `disease_risk` | **ensemble-vote** outbreak risk |
| **CompoundEventAgent** | `agents/compound.py` | flood/disease/glof/anomaly | — | `compound_threats` | co-occurrence fusion + **ensemble-vote** |

**Safety rule:** the LLM *augments* reasoning (summaries, confidence, causal
attribution) but **never gates safety decisions** — alert severity, phase
thresholds (`config.py`), and the deterministic flood probability that drives
routing are computed without the LLM.

---

## Shared reasoning core

- **Provider abstraction** — `llm/providers.py`: `LLMProvider` protocol +
  `AnthropicProvider` (Claude, `messages.parse` structured output, adaptive
  thinking) + `GeminiProvider` + `NullProvider`. SDKs are lazy-imported;
  `make_provider()` reads config/env. `FloodLLMClient` (`llm/client.py`)
  delegates to the provider and adds `available()` / `analyze()` / `critique()`.
- **Core-3 helpers on `BaseAgent`** (inherited by every agent):
  - `_run_with_reflexion(system, data, context, schema, mock, ...)` — analyze →
    self-critique → retry on low confidence.
  - `_ensemble_vote(system, data, context, schema, mock, runs=3)` — N-run
    median consensus for high-stakes predictions.
  - `_quantify_uncertainty(samples, ensemble_spread=...)` — pure-Python
    epistemic + aleatoric bounds (`UncertaintyBounds`); works with no key.
  - All three return the caller's `mock` when no LLM is configured.
- **Models** — `models/reasoning.py` (`ReasonedAssessment`, `UncertaintyBounds`),
  `models/compound.py` (`CompoundThreat`). Prompts in `llm/prompts.py`.

---

## Orchestrator & API

- `orchestrator/service.py` subscribes (awaited) to agent channels, records into
  `FloodSystemState` (`models/state.py`), steps the LangGraph state machine, and
  broadcasts phase changes over WebSocket.
- `api/app.py` lifespan builds the bus, 8 agents (injected with the LLM client),
  the orchestrator, and bridges every `EventBus.emit` to all WS clients
  (`{type: channel, data: payload}`).
- Routes serve **live agent state when present, demo data on cold start**:
  - Live-wired: `/map/flood-zones` (merges live zone risk/reasoning),
    `/ensemble/members`, `/ensemble/disagreement`, `/flood/compound`.
  - Demo-only (future live wiring): `/ensemble/fan`, `/timeline/frames`,
    `/scenario/run` — these need percentile/perturbation fields the current
    models don't yet carry.

---

## Adding a new agent

Follow the `/project:add-agent` workflow: define output models in
`models/<agent>.py` (every numeric prediction needs `confidence` + uncertainty
bounds; geo via `models/geo.py`; `created_at` + `agent_id` on every model),
implement `agents/<agent>.py` (use the inherited core-3 helpers with a `mock`
fallback), add the system prompt to `llm/prompts.py`, register in
`orchestrator/service.py` + `api/app.py` lifespan + `models/state.py`, add tests
under `backend/tests/`, and update the table above.
