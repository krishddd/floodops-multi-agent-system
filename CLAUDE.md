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

**One-command run (Docker):** `docker compose up` (or `make up`) starts backend
:8000 + frontend :5173. The lean image runs with no keys; build the semantic-memory
variant with `docker compose build --build-arg INCLUDE_ML=true backend`.

---

## v5 — Google Flood Forecasting connector, runoff calibration, skill panel

- **Google Flood Forecasting API** (`connectors/googleflood.py`, 🔑 key-gated):
  the operational Nature-2024 LSTM model (floodforecasting.googleapis.com,
  free/CC BY 4.0, waitlist → `FLOODS_API_KEY`, the name Google's colab/docs use;
  legacy `GOOGLE_FLOOD_API_KEY` still honored and wins if both set). Sentinel
  polls flood status when keyed: every status → `external_hazards`;
  SEVERE/EXTREME in the basin bbox → anomaly boost (`ai_model_flood_forecast`,
  confidence 0.95 quality-verified / 0.75 otherwise, deduped per
  gauge+issued_time). The connector mirrors the **full colab surface**
  (`Google_Flood_Forecasting_API_Usage_Example.ipynb`), all paginated via
  `nextPageToken`: `get_gauges` / `get_flood_status` (the area search filters
  by `regionCode` — ISO-3166 `BASIN_REGION_CODE`, default `NP`; the live API
  rejects an `areaFilter` bbox with 400, so the basin bbox is applied
  client-side on gauge locations — status now also surfaces `inundation_map_set`
  + `notification_polygon_id`), `query_gauge_forecasts` (quantitative
  discharge/level forecasts w/ lead times — Hydrology Model API; `gaugeIds`
  must repeat per id, not nest a list), `get_gauge_models` (official
  warning/danger/extreme thresholds, batched 50), `get_significant_events`,
  `get_flash_floods`, `get_serialized_polygon` (KML geometry). Read-only routes
  (honest `available: false` until keyed): `/api/v1/hazards/googleflood`,
  `…/forecasts`, `…/significant-events`, `…/flash-floods`, and
  `/api/v1/basin/google-thresholds` (Google's official thresholds as an
  independent cross-check against our Weibull-fitted `/basin/thresholds`).
  **Verified live 2026-06-30** (Nepal pilot key, project allowlisted): 765
  national gauges → 178 in the Bagmati bbox, all endpoints 200. Only flood
  status is wired into the agent pipeline so far (significant-event fusion is a
  candidate for v6 — fusion schema not yet exercised).
- **Runoff calibration** (`hydrology/calibration.py`, keyless): pairs the
  Open-Meteo archive precipitation reanalysis
  (`OpenMeteoConnector.get_historical_precipitation`) with the GloFAS
  discharge record; routes each historical year through the SAME linear
  reservoir and fits `scale = median(observed/routed annual max)` (refused
  <10 paired years or outside [0.01, 100]). Predict memoizes it 24h and
  scales member peaks before depth conversion (Bagmati live fit: scale 0.575
  over 21 years). *Magnitude bias-correction only — joint k/coefficient
  estimation is v6.* Tests: `tests/test_v5.py`.
- **Forecast Skill & Benchmark panel** (`frontend/src/panels/skill-panel.js`):
  renders `/verification/skill` + `/basin/thresholds` with an honest
  MEASURED vs COLD-START PRIOR badge; sends `X-API-Key` when configured.

## v4 — Multi-model AI fleet, live hazard feeds, real ML, agency-ready ops

Reference standard: Nearing et al., *Global prediction of extreme floods in
ungauged watersheds*, Nature 627, 559–563 (2024), DOI 10.1038/s41586-024-07145-1
(local copy `global_flood_prediction_nature_2024.md`). All geo ops are WGS84.

- **Multi-model LLM fleet:** `github` provider (GitHub Models,
  `GITHUB_MODELS_TOKEN`, default `openai/gpt-4.1-mini`); module-level
  **429-cooldown guard** (`CooldownProvider`, `LLM_RATE_LIMIT_COOLDOWN_S`,
  event-loop-only state — single Uvicorn worker for the LLM fleet);
  **heterogeneous `_ensemble_vote`** round-robins N runs across
  `LLM_ENSEMBLE_PROVIDERS` with pinned aggregation (median floats, plurality
  Enum/Literal, free text whole from the median-confidence run, ties → lower
  pool index); `FloodLLMClient` chains primary → extras on cooldown (loud,
  never silent-Null); per-agent routing in the lifespan (Groq fast lane =
  sentinel, GitHub deep lane = compound/urban). **Tier honesty:** Groq/GitHub
  free tiers are demo/eval — agency deployment swaps paid endpoints by config.
- **Live hazard connectors:** `connectors/gdacs.py` (keyless GeoJSON flood
  events, Green/Orange/Red severity map; research-use ToS — agencies need a
  data agreement). Sentinel polls it on CRON → `external_hazards` channel
  (fused by CompoundEventAgent as `regional_flood_alert`) + an anomaly boost
  when an Orange/Red event bbox intersects the basin bbox (rect approximation,
  `BASIN_BBOX_HALF_DEG`). `connectors/reliefweb.py` (v2 API, needs a free
  registered `RELIEFWEB_APPNAME`; payloads carry `report_lag_days` and are
  labelled retrospective-only) → DiseaseRiskAgent LLM context.
- **Real ML in agents:** `hydrology/climatology.py` — day-of-year discharge
  baselines (±15-day pooling over the multi-decade reanalysis, 24h memo);
  sentinel scores the live GloFAS forecast as **seasonal z-scores** (stub
  fallback kept). `hydrology/runoff.py` — member-seeded `Uniform(1±0.20)`
  precip perturbation routed through a delayed linear reservoir
  (`tp = 0.5·sqrt(area)`, `RUNOFF_RECESSION_K`); depth via the basin's fitted
  return-period scale; catchment area from `BASIN_EFFECTIVE_AREA_KM2` (≈585,
  upper Bagmati — NOT the bbox, which would overstate ~20×). *Physically
  motivated, uncalibrated — calibration is v5.* `obs/verification.py` — crash-
  proof asyncio loop (lifespan task, `VERIFICATION_JOB_INTERVAL_S`) scoring
  matured forecasts with the paper's **±2-day exceedance-hit rule**; serves
  measured P/R/F1 per return period, cold-start prior below
  `VERIFICATION_MIN_SAMPLES`.
- **Agency ops:** `obs/store.py` — WAL SQLite via `asyncio.to_thread`
  (forecasts/alerts/audit/verification_samples; **single-node/eval — production
  = PostgreSQL**, schema kept portable). `models/cap.py` — **CAP 1.2 XML**
  export (`GET /api/v1/alerts/{id}/cap.xml`), ElementTree-built (auto-escaped,
  external strings length-capped). Optional **API auth**: `FLOODOPS_API_KEY` →
  `X-API-Key` on `/api/v1/*`, `?api_key=` on the WS upgrade (1008 on mismatch).
  Routes: `/api/v1/verification/skill` (cold-start contract: 200 + prior),
  `/api/v1/basin/thresholds`, `/api/v1/hazards/gdacs`. Rate limiting, full
  AuthN/Z, HA: documented out-of-scope. Tests: `tests/test_v4.py`.

## v3 — Real flood-frequency analysis + free-tier LLM providers

- **Per-basin return-period thresholds (paper-faithful, keyless):**
  `floodops/hydrology/return_periods.py` fits 1/2/5/10-yr discharge thresholds
  from the 1984→present GloFAS reanalysis (Weibull plotting positions on annual
  maxima, Bulletin 17B framing — the method Nearing et al., Nature 627, 2024
  derive per-gauge events with). `OpenMeteoConnector.get_historical_discharge()`
  serves the record keyless (24h cache); FloodPredictAgent fits + caches the
  thresholds per basin (24h) and attaches a deterministic **GloFAS benchmark
  reference** to every forecast (`benchmark_discharge_thresholds_m3s`,
  `benchmark_peak_discharge_m3s`, `benchmark_return_period_years`). Refused
  (None) below 10 years of record — never faked. Streamflow remains
  **reference-only, never a model input** (paper safety rule). The depth-based
  `RETURN_PERIOD_DEPTH_THRESHOLDS_M` constants still drive the mock-ensemble
  classification; the benchmark fields carry the real basin-specific science.
  Tests: `tests/test_hydrology.py`.
- **OpenAI-compatible LLM providers:** `OpenAICompatProvider` (`llm/providers.py`)
  speaks `/chat/completions` over httpx (no SDK) — covers **Groq**
  (`GROQ_API_KEY`, default `llama-3.3-70b-versatile`), **OpenRouter**
  (`OPENROUTER_API_KEY`) and any custom endpoint (`OPENAI_COMPAT_*`, e.g. local
  Ollama). `FLOODOPS_LLM_PROVIDER` now accepts
  `anthropic|gemini|groq|openrouter|openai-compat|auto`; auto order is
  Anthropic → Gemini → Groq → OpenRouter → compat → Null.

## v2 — Live command deck, observability, real connectors, CI/CD

- **Live WebSocket command deck** (frontend): every agent channel is broadcast as a
  typed `{type, data, ts}` envelope and surfaced live — a **Compound Threat Radial**
  (signature canvas), an **Agent Activity Stream**, a **Sitrep ticker**, and a
  connection HUD with reconnect + full snapshot resync. Works keyless (the basemap
  needs a Google Maps key; the panels do not).
- **Observability:** `GET /health` (agents + per-connector live/mock + LLM status),
  `GET /metrics` (Prometheus via `prometheus_client`), structured JSON logging
  (`floodops/obs/`). **`# NOTE: dev-only` — `/metrics` counters and the agent-memory
  store are in-memory and reset on restart; durable persistence is out of scope for v2.**
- **Keyless real connectors:** `OpenMeteoConnector` (GloFAS discharge ensemble +
  rainfall, TTL 900s) feeds predict/sentinel; `OSMConnector` (Overpass, TTL 86400s)
  feeds urban. Both fall back to mock when unreachable. Heavy GDAL connectors live
  behind the same interface (`requirements-geo.txt`); a key activates them later.
- **Advanced agent techniques:** bounded FIFO **agent memory** (`MEMORY_MAX_EVENTS`,
  default 500) with cosine recall — embeddings via sentence-transformers when present,
  else recall is **disabled (never faked)**; a config-seeded **causal graph**
  (`WATERSHED_TOPOLOGY`, default **`bagmati`** — change `DEFAULT_WATERSHED_REGION` for
  another basin); multi-scale district rollup in urban.
- **CI/CD:** GitHub Actions (`ci.yml`: ruff + advisory mypy + pytest-cov, eslint +
  vitest + build, **blocking security gate** — bandit HIGH + `npm audit --omit=dev
  --audit-level=high`; `docker.yml`: matrix lean+ML backend + frontend). `make
  test lint security`, ruff/mypy/eslint/prettier/pre-commit configs, vitest panel tests.

**v2 scope notes / tradeoffs (for v3):**
- **Persistence is out of scope** — agent memory + metrics reset on restart.
- **Optional semantic memory:** install `sentence-transformers` (in `requirements-ml.txt`,
  or Docker `--build-arg INCLUDE_ML=true` which pre-downloads `all-MiniLM-L6-v2`) for
  keyless semantic recall; without it `recall_similar()` returns `[]`.
- **`LLM_ENSEMBLE_CONCURRENCY`** (default 1) caps concurrent LLM calls for tier-1 RPM
  safety; in no-key/dev mode raise it freely (NullProvider makes no network calls).
- **Memory uses FIFO eviction** — it can evict the exact high-value old analogue (e.g.
  a 2021 monsoon) first; v3 may move to LRU/relevance-scored.
- **Phase transitions (v3, FIXED):** `orchestrator/service.py` now advances phases via
  a deterministic **one-shot single-step** transition (`_step_graph` evaluates one
  routing decision per event using the graph's own routing/node functions) instead of
  re-invoking the LangGraph from its fixed `monitoring` entry point (which reset the
  phase and hit `GraphRecursionError`). It also subscribes to `anomaly_alerts` and
  `flood_receding` — without these the MONITORING→ELEVATED and ACTIVE→POST_FLOOD
  transitions could never fire. Covered by `tests/test_orchestrator.py`.

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
