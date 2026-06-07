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
