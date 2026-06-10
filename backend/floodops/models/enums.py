"""
Core enumerations used across the entire FloodOps system.

These enums define the vocabulary of the system — every agent, every
phase transition, and every data model references these types.
"""

from __future__ import annotations

from enum import StrEnum


class FloodPhase(StrEnum):
    """The 7 lifecycle phases of a flood event.

    The orchestrator's LangGraph state machine transitions through these
    phases based on agent outputs and gate conditions.
    """

    MONITORING = "00_MONITORING"   # 24/7 baseline — always on
    ELEVATED = "01_ELEVATED"       # T−72h to T−48h — anomaly detected
    IMMINENT = "02_IMMINENT"       # T−12h to T−24h — probability > 70%
    EVACUATION = "03_EVACUATION"   # T−2h to T−6h — probability > 90% or GLOF breach
    ACTIVE = "04_ACTIVE"           # T=0 to T+24h — flood confirmed
    POST_FLOOD = "05_POST_FLOOD"   # T+24h to T+14d — water receding
    RECOVERY = "06_RECOVERY"       # T+14d onwards — rebuild and learn


class AlertLevel(StrEnum):
    """Anomaly severity levels from SentinelAgent.

    Based on z-score deviation from rolling baseline.
    Thresholds are configured in config.ANOMALY_THRESHOLDS.
    """

    LOW = "LOW"           # > 1.5σ deviation
    MEDIUM = "MEDIUM"     # > 2.5σ deviation
    HIGH = "HIGH"         # > 3.5σ deviation
    CRITICAL = "CRITICAL" # > 5σ deviation OR confirmed GLOF signals


class SeverityLevel(StrEnum):
    """Alert dissemination severity from AlertAgent.

    Maps flood probability to communication channel escalation.
    """

    ADVISORY = "ADVISORY"    # < 40% probability — app/email only
    WATCH = "WATCH"          # 40–70% probability — SMS to high-risk zones
    WARNING = "WARNING"      # 70–90% probability — mass cell broadcast
    EMERGENCY = "EMERGENCY"  # > 90% probability OR GLOF breach — all channels


class TriggerType(StrEnum):
    """How an agent is activated.

    Each agent declares one or more trigger types:
    - CRON: scheduled periodic execution (SentinelAgent, GLOFAgent)
    - QUEUE: reactive to events from other agents (most agents)
    - HTTP_DIRECT: synchronous bypass for time-critical paths (GLOF → Alert)
    """

    CRON = "CRON"
    QUEUE = "QUEUE"
    HTTP_DIRECT = "HTTP_DIRECT"


class Pathogen(StrEnum):
    """Post-flood waterborne pathogens tracked by DiseaseRiskAgent.

    Each has a distinct incubation period and risk model:
    - Cholera: 2–5 day incubation
    - Typhoid: 6–30 day incubation
    - Leptospirosis: 2–30 day incubation
    """

    CHOLERA = "cholera"
    TYPHOID = "typhoid"
    LEPTOSPIROSIS = "leptospirosis"


class DataSource(StrEnum):
    """External data sources with their true update cadences.

    Used by data-cadence badges to honestly display freshness.
    """

    USGS_GAUGES = "USGS_GAUGES"           # 🟢 15 min
    NWS_ALERTS = "NWS_ALERTS"             # 🟢 15 min
    NOAA_GOES = "NOAA_GOES"               # 🟢 15 min
    ECMWF_ENSEMBLE = "ECMWF_ENSEMBLE"     # 🟡 6-hourly
    SENTINEL_SAR = "SENTINEL_SAR"         # 🟡 6–12 day revisit
    SENTINEL_OPTICAL = "SENTINEL_OPTICAL" # 🟡 5–10 day revisit
    SOIL_MOISTURE = "SOIL_MOISTURE"       # 🟡 daily
    GLIMS = "GLIMS"                       # ⚪ static inventory
    OSM = "OSM"                           # 🔵 on-demand
    WORLDPOP = "WORLDPOP"                 # ⚪ annual
    HYDROSHEDS = "HYDROSHEDS"             # ⚪ static
    DARTMOUTH = "DARTMOUTH"               # ⚪ event-based archive
    GDACS = "GDACS"                       # 🟢 continuous global alerts (v4)
    RELIEFWEB = "RELIEFWEB"               # 🟡 daily, days-old reports (v4)


class ConnectorStatus(StrEnum):
    """Connector health status."""

    LIVE = "LIVE"       # 🟢 Real API, actively fetching
    MOCK = "MOCK"       # ⚪ Returning realistic stubs
    ERROR = "ERROR"     # 🔴 Connector failed health check
    STALE = "STALE"     # 🟡 Data older than expected cadence
