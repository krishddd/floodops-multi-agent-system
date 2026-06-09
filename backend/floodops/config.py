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
# Which provider the reasoning core targets: "anthropic" | "gemini" | "auto".
# "auto" picks the first provider whose key is set, else a no-op NullProvider.
FLOODOPS_LLM_PROVIDER: str = os.getenv("FLOODOPS_LLM_PROVIDER", "auto")
# Default model ids per provider (overridable via env).
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Effort for adaptive-thinking Anthropic calls: low | medium | high | xhigh | max
ANTHROPIC_EFFORT: str = os.getenv("ANTHROPIC_EFFORT", "medium")

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
# API / Server
# ---------------------------------------------------------------------------
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
WS_BROADCAST_INTERVAL_MS: int = 500  # WebSocket broadcast throttle
