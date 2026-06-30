"""
FloodOps system-wide configuration.

All thresholds, schedules, and constants are defined here.
Agent-specific logic reads from this module — no magic numbers in agent code.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment
# ---------------------------------------------------------------------------
_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# ---------------------------------------------------------------------------
# Google Cloud
# ---------------------------------------------------------------------------
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
GOOGLE_GENAI_API_KEY: str = os.getenv("GOOGLE_GENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# LLM reasoning core (provider-agnostic)
# ---------------------------------------------------------------------------
# Anthropic (Claude). Key added later by the operator — degrades gracefully.
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
# Which provider the reasoning core targets:
#   "anthropic" | "gemini" | "groq" | "openrouter" | "auto".
# "auto" picks the first provider whose key is set, else a no-op NullProvider.
FLOODOPS_LLM_PROVIDER: str = os.getenv("FLOODOPS_LLM_PROVIDER", "auto")
# Default model ids per provider (overridable via env).
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# OpenAI-compatible backends (free-tier friendly): Groq (LPU-fast open-weight
# models) and OpenRouter (single key, any frontier model). Both speak the
# /chat/completions wire format so one provider class covers them — and any
# other compatible endpoint via the OPENAI_COMPAT_* overrides.
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENAI_COMPAT_BASE_URL: str = os.getenv("OPENAI_COMPAT_BASE_URL", "")
OPENAI_COMPAT_API_KEY: str = os.getenv("OPENAI_COMPAT_API_KEY", "")
OPENAI_COMPAT_MODEL: str = os.getenv("OPENAI_COMPAT_MODEL", "")
# GitHub Models (v4): OpenAI-compatible gateway authenticated with a GitHub PAT.
# Free tier = demo/eval; agency deployment swaps to a paid endpoint via config.
GITHUB_MODELS_TOKEN: str = os.getenv("GITHUB_MODELS_TOKEN", "")
GITHUB_MODELS_MODEL: str = os.getenv("GITHUB_MODELS_MODEL", "openai/gpt-4.1-mini")

# NVIDIA NIM (build.nvidia.com / integrate.api.nvidia.com) — an OpenAI-compatible
# gateway hosting open-weight frontier models (GLM, MiniMax, …). Wired as extra
# FALLBACK voters: when the primary/free-tier providers 429 or hit a token
# limit, the provider chain falls through to these (and they also join the
# ensemble-vote pool). Keys are added later in .env; until then available() is
# False and the providers are skipped. Two models are pre-wired:
#   nvidia          → NVIDIA_MODEL          (default z-ai/glm-5.1)
#   nvidia-minimax  → NVIDIA_MINIMAX_MODEL  (default minimaxai/minimax-m2.7)
# The MiniMax key is optional — it falls back to NVIDIA_API_KEY when unset (NIM
# keys typically authorize every model on the endpoint).
NVIDIA_BASE_URL: str = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_MODEL: str = os.getenv("NVIDIA_MODEL", "z-ai/glm-5.1")
NVIDIA_MINIMAX_API_KEY: str = os.getenv("NVIDIA_MINIMAX_API_KEY", "")
NVIDIA_MINIMAX_MODEL: str = os.getenv("NVIDIA_MINIMAX_MODEL", "minimaxai/minimax-m2.7")

# v4 — rate-limit cooldown for free-tier providers: a 429 marks the backend
# unavailable for this many seconds; callers fall through the provider chain
# (never silently to Null — the final fallback is the deterministic mock).
LLM_RATE_LIMIT_COOLDOWN_S: float = float(os.getenv("LLM_RATE_LIMIT_COOLDOWN_S", "300"))
# v4 — heterogeneous ensemble-vote pool: comma-separated extra provider names
# (e.g. "groq,github") whose models vote alongside the primary provider.
# Empty = single-provider ensemble (pre-v4 behavior).
LLM_ENSEMBLE_PROVIDERS: str = os.getenv("LLM_ENSEMBLE_PROVIDERS", "")
# Effort for adaptive-thinking Anthropic calls: low | medium | high | xhigh | max
ANTHROPIC_EFFORT: str = os.getenv("ANTHROPIC_EFFORT", "medium")

# Max attempts for a single LLM call on transient (503/429/overloaded) errors —
# free Gemini tiers 503 under load, so a couple of backoff retries smooths it out.
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

# Core-3 technique tuning (used by BaseAgent reasoning helpers).
LLM_ENSEMBLE_RUNS: int = int(os.getenv("LLM_ENSEMBLE_RUNS", "3"))
LLM_REFLEXION_MAX_RETRIES: int = int(os.getenv("LLM_REFLEXION_MAX_RETRIES", "3"))
LLM_CONFIDENCE_FLOOR: float = float(os.getenv("LLM_CONFIDENCE_FLOOR", "0.75"))

# Reasoning resilience (v2): per-call timeout and an outer cap on the whole
# reflexion loop so a slow/unavailable LLM can never starve an agent's event
# loop slot — both fall back to the caller's deterministic mock on expiry.
LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
LLM_REFLEXION_TOTAL_TIMEOUT_SECONDS: float = float(
    os.getenv("LLM_REFLEXION_TOTAL_TIMEOUT_SECONDS", "120")
)
# Shared cap on concurrent LLM calls across ALL agents (default 1 = sequential,
# safe for tier-1 RPM limits). The semaphore is created lazily in the app
# lifespan; raise freely in no-key/dev mode (NullProvider makes no network calls).
LLM_ENSEMBLE_CONCURRENCY: int = int(os.getenv("LLM_ENSEMBLE_CONCURRENCY", "1"))

# Agent memory (v2, dev-only / not restart-safe): bounded FIFO vector store.
MEMORY_MAX_EVENTS: int = int(os.getenv("MEMORY_MAX_EVENTS", "500"))

# CompoundEventAgent correlation window (v2).
COMPOUND_WINDOW_HOURS: float = float(os.getenv("COMPOUND_WINDOW_HOURS", "6"))

# Return-period event thresholds (v3, paper-aligned). Nearing et al., Nature 627
# (2024) frame flood skill by return period (1/2/5/10-yr) rather than raw depth.
# These map a return-period to the peak-depth (m) that defines that event in the
# demo basin. NOTE: dev-only coarse values — the paper derives per-gauge thresholds
# from a Bulletin 17B flood-frequency fit on the observed record; swap these for
# basin-specific values when real GRDC/discharge data is wired.
RETURN_PERIOD_DEPTH_THRESHOLDS_M: dict[int, float] = {
    1: 0.5,
    2: 1.0,
    5: 2.0,
    10: 3.0,
}
# Fraction of ensemble members that must exceed a return-period threshold for it
# to be reported as the forecast's headline return-period event (deterministic,
# never LLM-gated — mirrors the paper's member-agreement framing).
RETURN_PERIOD_MEMBER_AGREEMENT: float = float(
    os.getenv("RETURN_PERIOD_MEMBER_AGREEMENT", "0.5")
)

# Lead-time forecast skill (v3, paper-aligned). The headline result of Nearing
# et al. (2024) is that AI forecasts retain skill out to ~5-day lead time —
# matching GloFAS *nowcasts* (0-day) — which lets warnings go out earlier.
#
# These encode that finding as a deterministic reference curve so each forecast
# can report an "effective warning horizon". They are ILLUSTRATIVE reference
# values distilled from the paper (F1 by return period falls in ~0.15–0.55;
# skill is retained to day 5 then degrades), NOT a live skill measurement — a
# real deployment would read empirical per-gauge F1 from a hindcast archive.

# Reference nowcast (0-day) F1 by return period. Rarer events score lower
# (paper Fig 2/4): more impactful but harder to predict.
RETURN_PERIOD_BASE_F1: dict[int, float] = {
    1: 0.55,
    2: 0.45,
    5: 0.35,
    10: 0.28,
}
# Fraction of nowcast F1 retained at lead days 0..7. AI ~day-5 ≈ GloFAS day-0,
# so skill holds through day 5 then drops (paper Fig 3).
LEAD_TIME_SKILL_RETENTION: list[float] = [1.0, 0.99, 0.97, 0.94, 0.90, 0.85, 0.72, 0.58]
# Minimum estimated F1 for a lead day to count toward the warning horizon.
SKILLFUL_F1_THRESHOLD: float = float(os.getenv("SKILLFUL_F1_THRESHOLD", "0.2"))

# v4 — demo basin centre (Bagmati/Kathmandu) and its approximate bbox half-width
# in degrees. The basin bbox is [lat ± half, lng ± half] — a documented
# rectangle approximation used for GDACS cross-validation overlap checks.
BASIN_CENTER_LAT: float = float(os.getenv("BASIN_CENTER_LAT", "27.7"))
BASIN_CENTER_LNG: float = float(os.getenv("BASIN_CENTER_LNG", "85.3"))
BASIN_BBOX_HALF_DEG: float = float(os.getenv("BASIN_BBOX_HALF_DEG", "1.0"))
# ISO 3166-1 alpha-2 country code for the basin's region. The Google Flood
# Forecasting API filters its area searches by regionCode (NOT a bbox); the
# connector queries this region then filters to the basin bbox client-side.
# Default "NP" = Nepal (the Bagmati demo basin).
BASIN_REGION_CODE: str = os.getenv("BASIN_REGION_CODE", "NP")

# v4 — physically-motivated runoff ensemble (uncalibrated defaults, see
# hydrology/runoff.py): member precip perturbation spread and the linear-
# reservoir recession coefficient.
ENSEMBLE_SPREAD: float = float(os.getenv("ENSEMBLE_SPREAD", "0.20"))
RUNOFF_RECESSION_K: float = float(os.getenv("RUNOFF_RECESSION_K", "0.3"))
# Effective hydrological catchment area (km²) used for runoff routing — NOT the
# alert bbox. Default ≈ the upper Bagmati at Chobar (~585 km², demo basin);
# set per deployment. The bbox is for alert geometry only: using its area
# (~11,000 km² at 1°) would overstate discharge by ~20× against the GloFAS
# cell the return-period thresholds are fitted to.
BASIN_EFFECTIVE_AREA_KM2: float = float(os.getenv("BASIN_EFFECTIVE_AREA_KM2", "585"))

# v4 — forecast verification loop (paper's ±2-day exceedance-hit rule).
VERIFICATION_JOB_INTERVAL_S: float = float(os.getenv("VERIFICATION_JOB_INTERVAL_S", "3600"))
VERIFICATION_MIN_SAMPLES: int = int(os.getenv("VERIFICATION_MIN_SAMPLES", "20"))

# Watershed flow topology for causal-graph reasoning (v2). Config-driven adjacency
# (upstream -> downstream), keyed by region id, configurable per-region. This is
# the SOLE source of topology — change DEFAULT_WATERSHED_REGION (or add a region)
# when deploying outside the Kathmandu/Bagmati demo basin.
DEFAULT_WATERSHED_REGION: str = os.getenv("DEFAULT_WATERSHED_REGION", "bagmati")
WATERSHED_TOPOLOGY: dict[str, list[tuple[str, str]]] = {
    # Bagmati basin (Kathmandu valley) — coarse demo topology.
    "bagmati": [
        ("Shivapuri_headwaters", "Bagmati_upper"),
        ("Bagmati_upper", "Bagmati_Pashupati"),
        ("Bagmati_Pashupati", "Bagmati_Chobar"),
        ("Bishnumati_tributary", "Bagmati_Chobar"),
        ("Bagmati_Chobar", "Bagmati_outlet"),
    ],
}

# ---------------------------------------------------------------------------
# External data connectors
# ---------------------------------------------------------------------------
API_USGS_PAT: str = os.getenv("API_USGS_PAT", "")
SENTINEL_HUB_CLIENT_ID: str = os.getenv("SENTINEL_HUB_CLIENT_ID", "")
SENTINEL_HUB_CLIENT_SECRET: str = os.getenv("SENTINEL_HUB_CLIENT_SECRET", "")
ECMWF_CDS_TOKEN: str = os.getenv("ECMWF_CDS_TOKEN", "")

# ---------------------------------------------------------------------------
# Anomaly detection thresholds (z-score σ)
# Maps SeverityLevel enum → minimum abs(z-score) required
# ---------------------------------------------------------------------------
ANOMALY_THRESHOLDS: dict[str, float] = {
    "LOW": 1.5,       # > 1.5σ
    "MEDIUM": 2.5,    # > 2.5σ
    "HIGH": 3.5,      # > 3.5σ
    "CRITICAL": 5.0,  # > 5σ or confirmed GLOF signals
}

# ---------------------------------------------------------------------------
# Phase transition probability thresholds
# ---------------------------------------------------------------------------
PROB_ELEVATED: float = 0.0       # Any MEDIUM+ alert triggers elevated
PROB_IMMINENT: float = 0.70      # FloodPredictAgent probability > 70%
PROB_EVACUATION: float = 0.90    # Probability > 90% OR GLOF breach
PROB_RESOURCE_TRIGGER: float = 0.50  # ResourceAgent pre-positions at > 50%
PROB_ADVISORY: float = 0.40      # AlertAgent ADVISORY threshold
PROB_WATCH: float = 0.40         # AlertAgent WATCH threshold
PROB_WARNING: float = 0.70       # AlertAgent WARNING threshold
PROB_EMERGENCY: float = 0.90     # AlertAgent EMERGENCY threshold

# ---------------------------------------------------------------------------
# GLOF dam integrity
# ---------------------------------------------------------------------------
GLOF_BREACH_THRESHOLD: float = 0.3   # Integrity < 0.3 = breach imminent
GLOF_VOLUME_ALERT_FACTOR: float = 1.2  # Volume delta > 20% of baseline

# ---------------------------------------------------------------------------
# CRON schedules
# ---------------------------------------------------------------------------
CRON_SENTINEL_WEATHER: str = "*/15 * * * *"     # Every 15 minutes
CRON_SENTINEL_GAUGES: str = "*/15 * * * *"      # Every 15 minutes
CRON_GLOF_LAKES: str = "0 6 */6 * *"            # Every 6 days at 06:00
CRON_URBAN_RISK_REFRESH: str = "0 0 * * *"      # Daily at midnight

# ---------------------------------------------------------------------------
# Pre-positioning
# ---------------------------------------------------------------------------
PREPOSITION_MIN_HOURS_TO_PEAK: float = 12.0  # Must have 12+ hours to peak
PREPOSITION_MAX_TRAVEL_HOURS: float = 1.0    # Staging within 1h drive

# ---------------------------------------------------------------------------
# Disease risk
# ---------------------------------------------------------------------------
DISEASE_RISK_HOTSPOT_THRESHOLD: float = 0.7  # Risk > 0.7 triggers supply order

# ---------------------------------------------------------------------------
# De-escalation
# ---------------------------------------------------------------------------
DEESCALATION_GAUGE_HOURS: int = 4  # Gauge dropping 4+ consecutive hours → post-flood

# ---------------------------------------------------------------------------
# Timeline / ensemble
# ---------------------------------------------------------------------------
TIMELINE_HISTORY_HOURS: int = 72     # 3 days of history
TIMELINE_FORECAST_HOURS: int = 240   # 10 days of forecast
ENSEMBLE_MEMBER_COUNT: int = 50      # ECMWF ensemble members
ENSEMBLE_REPRESENTATIVE_COUNT: int = 10  # k-means clustered for spaghetti plot

# ---------------------------------------------------------------------------
# v4 — persistence + API auth
# ---------------------------------------------------------------------------
# SQLite is single-node/evaluation persistence; production = PostgreSQL via an
# async driver (schema kept portable). Empty value disables persistence.
FLOODOPS_DB_PATH: str = os.getenv("FLOODOPS_DB_PATH", "floodops.db")
# When set, /api/v1/* requires the X-API-Key header and the WebSocket upgrade
# requires ?api_key=… (browsers cannot set WS headers). Unset = open dev mode.
FLOODOPS_API_KEY: str = os.getenv("FLOODOPS_API_KEY", "")

# ---------------------------------------------------------------------------
# API / Server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
WS_BROADCAST_INTERVAL_MS: int = 500  # WebSocket broadcast throttle
