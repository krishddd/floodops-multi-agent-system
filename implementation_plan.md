# FloodOps Multi-Agent Orchestration System — Implementation Plan v2

A production-grade, multi-agent flood monitoring, prediction, and response system with **real-time Google Maps visualization**, **LLM-powered reasoning**, **Google Workspace integration**, and **10 external data connectors**. 8 agents operate across 7 cascading phases.

---

## User Review Required

> [!IMPORTANT]
> **Major scope additions in v2:**
> 1. **Real-time Google Maps frontend** — live flood zone overlays, evacuation routes, sensor markers, heatmaps
> 2. **Google OAuth 2.0 + Workspace** — Sheets for data logging, Drive for reports, Gmail for alert emails
> 3. **LLM reasoning layer** — Gemini-powered situational analysis, anomaly interpretation, decision justification
> 4. **10 external data connectors** — real API integrations with exact endpoints, auth, and rate limiting

> [!WARNING]
> **Google Maps API Key required**: You must create a Google Cloud project and enable Maps JavaScript API, Geocoding API, and Routes API. The free tier provides 10,000 map loads/month. See the [Connector Setup Guide](#connector-setup--credentials) below.

> [!WARNING]
> **Copernicus / ECMWF accounts required**: Sentinel Hub and ECMWF CDS require free registration AND manual Terms of Use acceptance per dataset before API access works.

> [!IMPORTANT]
> **All agents in Python**: AlertAgent will be Python (not TypeScript) for this build. The frontend visualization is a separate Vite app communicating via WebSocket/REST with the Python backend.

## Open Questions

1. **Which LLM provider?** Plan assumes **Google Gemini** (via `google-genai` SDK) since you're already in Google ecosystem. Want OpenAI/Anthropic as fallback?

2. **Google Earth Engine**: Sources 6 (GLIMS), 9 (HydroSHEDS), and 10 (Dartmouth) are best accessed via GEE. Do you have a GEE account, or should I use direct file downloads instead?

3. **Deployment target**: Is this running locally for now, or do you want Docker/Cloud Run scaffolding from the start?

4. **Real-time refresh rate**: How often should the Maps frontend poll for updates? Plan assumes 30-second intervals via WebSocket push.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND (Vite + Google Maps JS API)         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────────┐  │
│  │ Map View │ │ Layers   │ │ Dashboard│ │ LLM Chat Panel    │  │
│  │ GeoJSON  │ │ Toggle   │ │ Metrics  │ │ "Explain this     │  │
│  │ Overlays │ │ Heatmap  │ │ Gauges   │ │  flood scenario"  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────────────┘  │
│         ▲ WebSocket (live flood data, phase transitions)       │
├─────────┼──────────────────────────────────────────────────────┤
│         ▼                                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              BACKEND (FastAPI + LangGraph)               │   │
│  │  ┌──────────────┐  ┌─────────────┐  ┌───────────────┐  │   │
│  │  │ REST API     │  │ WebSocket   │  │ Google OAuth   │  │   │
│  │  │ /api/v1/*    │  │ /ws/flood   │  │ /auth/*        │  │   │
│  │  └──────┬───────┘  └──────┬──────┘  └───────┬───────┘  │   │
│  │         │                 │                  │          │   │
│  │  ┌──────▼─────────────────▼──────────────────▼───────┐  │   │
│  │  │           FloodOps Orchestrator (LangGraph)        │  │   │
│  │  │  7-phase state machine + LLM reasoning layer       │  │   │
│  │  └──────┬─────────────────┬──────────────────┬───────┘  │   │
│  │         │    EventBus     │                  │          │   │
│  │  ┌──────▼───┐ ┌──────────▼──┐ ┌─────────────▼──────┐  │   │
│  │  │ 8 Agents │ │ Connectors  │ │ Google Workspace   │  │   │
│  │  │ Sentinel │ │ NOAA, USGS  │ │ Sheets, Drive,     │  │   │
│  │  │ GLOF     │ │ ESA, ECMWF  │ │ Gmail              │  │   │
│  │  │ Predict  │ │ OSM, WorldPop│ │                    │  │   │
│  │  │ Urban    │ │ HydroSHEDS  │ │                    │  │   │
│  │  │ Alert    │ │ GLIMS, DFO  │ │                    │  │   │
│  │  │ Resource │ │ Soil Moist. │ │                    │  │   │
│  │  │ Disease  │ │             │ │                    │  │   │
│  │  └──────────┘ └─────────────┘ └────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
flood_multi-agent_system/
├── flood_agent_specs.jsx                    # [EXISTING]
├── flood_multiagent_orchestration.html      # [EXISTING]
│
├── backend/                                 # [NEW] Python backend
│   ├── pyproject.toml
│   ├── requirements.txt
│   │
│   ├── floodops/
│   │   ├── __init__.py
│   │   ├── config.py                        # Thresholds, API keys, schedules
│   │   │
│   │   ├── models/                          # Pydantic data models
│   │   │   ├── __init__.py
│   │   │   ├── enums.py                     # FloodPhase, AlertLevel, etc.
│   │   │   ├── state.py                     # FloodSystemState (LangGraph)
│   │   │   ├── sentinel.py                  # AnomalyAlert, SensorReading
│   │   │   ├── glof.py                      # LakeHealthReport, ImpactZone
│   │   │   ├── predict.py                   # ProbabilisticFloodMap, FloodForecast
│   │   │   ├── urban.py                     # ZoneRiskReport, RouteSet
│   │   │   ├── alert.py                     # CellBroadcast, RadioBroadcast
│   │   │   ├── resource.py                  # LogisticsOrders, RescueRoutes
│   │   │   ├── disease.py                   # DiseaseRiskMap, HotspotList
│   │   │   ├── orchestrator.py              # AuditEntry, StateTransition
│   │   │   └── geo.py                       # GeoJSON models, BBox, Coordinate
│   │   │
│   │   ├── queue/                           # Event bus
│   │   │   ├── __init__.py
│   │   │   └── event_bus.py                 # emit/subscribe/direct_call
│   │   │
│   │   ├── agents/                          # 8 agent implementations
│   │   │   ├── __init__.py
│   │   │   ├── base.py                      # BaseAgent ABC
│   │   │   ├── sentinel.py
│   │   │   ├── glof.py
│   │   │   ├── predict.py
│   │   │   ├── urban.py
│   │   │   ├── alert.py
│   │   │   ├── resource.py
│   │   │   └── disease.py
│   │   │
│   │   ├── orchestrator/                    # LangGraph state machine
│   │   │   ├── __init__.py
│   │   │   ├── graph.py                     # StateGraph definition
│   │   │   ├── nodes.py                     # Phase node functions
│   │   │   └── routing.py                   # Conditional edge routing
│   │   │
│   │   ├── connectors/                      # [NEW] External data connectors
│   │   │   ├── __init__.py
│   │   │   ├── base.py                      # BaseConnector ABC (rate limiting, retry, caching)
│   │   │   ├── noaa.py                      # NOAA GOES-16/17 + NWS Weather API
│   │   │   ├── usgs.py                      # USGS Water Services (river gauges)
│   │   │   ├── sentinel_hub.py              # ESA Sentinel-1 SAR + Sentinel-2
│   │   │   ├── ecmwf.py                     # ECMWF CDS ensemble forecasts
│   │   │   ├── soil_moisture.py             # ESA CCI Soil Moisture
│   │   │   ├── glims.py                     # GLIMS Glacier Database (WFS)
│   │   │   ├── osm.py                       # OpenStreetMap / Overpass API
│   │   │   ├── worldpop.py                  # WorldPop population density
│   │   │   ├── hydrosheds.py                # HydroSHEDS river network + basins
│   │   │   └── dartmouth.py                 # Dartmouth Flood Observatory
│   │   │
│   │   ├── llm/                             # [NEW] LLM reasoning layer
│   │   │   ├── __init__.py
│   │   │   ├── client.py                    # Gemini API client wrapper
│   │   │   ├── prompts.py                   # System prompts per agent/phase
│   │   │   └── reasoning.py                 # Situational analysis, decision justification
│   │   │
│   │   ├── auth/                            # [NEW] Google OAuth 2.0
│   │   │   ├── __init__.py
│   │   │   ├── oauth.py                     # OAuth flow (authorization code grant)
│   │   │   └── workspace.py                 # Sheets, Drive, Gmail wrappers
│   │   │
│   │   ├── api/                             # [NEW] FastAPI routes
│   │   │   ├── __init__.py
│   │   │   ├── app.py                       # FastAPI app, CORS, lifespan
│   │   │   ├── routes_flood.py              # /api/v1/flood/* endpoints
│   │   │   ├── routes_auth.py               # /auth/* OAuth endpoints
│   │   │   ├── routes_map.py                # /api/v1/map/* GeoJSON endpoints
│   │   │   └── websocket.py                 # /ws/flood WebSocket handler
│   │   │
│   │   └── main.py                          # Entry point
│   │
│   └── tests/
│       ├── __init__.py
│       ├── test_state_transitions.py
│       ├── test_event_bus.py
│       ├── test_agents.py
│       ├── test_connectors.py
│       ├── test_models.py
│       └── test_auth.py
│
├── frontend/                                # [NEW] Vite frontend
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.js                          # App entry
│   │   ├── map.js                           # Google Maps initialization + layers
│   │   ├── layers.js                        # Flood zone, evacuation, heatmap layers
│   │   ├── websocket.js                     # WebSocket client for live updates
│   │   ├── dashboard.js                     # Phase status, metrics panel
│   │   ├── chat.js                          # LLM chat panel
│   │   ├── auth.js                          # Google OAuth login flow
│   │   └── style.css                        # Dark theme, glassmorphism
│   └── public/
│       └── favicon.svg
│
├── .env.example                             # [NEW] Environment variables template
└── docker-compose.yml                       # [NEW] Optional containerization
```

---

## Proposed Changes

### Component 1: External Data Connectors (`backend/floodops/connectors/`)

The real data pipeline. Every connector extends `BaseConnector` which provides rate limiting, exponential backoff retry, response caching, and credential management.

---

#### [NEW] [base.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/base.py)

```python
class BaseConnector(ABC):
    """Base for all external data connectors.
    
    Provides:
    - Rate limiting (token bucket per connector)
    - Exponential backoff retry (max 3 retries, handles HTTP 429)
    - Response caching (TTL-based, configurable per connector)
    - Credential loading from environment / .env
    - Structured logging of all API calls
    """
    
    name: str
    base_url: str
    auth_method: Literal["none", "api_key", "oauth2", "token"]
    rate_limit_per_minute: int
    cache_ttl_seconds: int
    
    @abstractmethod
    async def health_check(self) -> bool: ...
    
    async def _request(self, method, path, **kwargs) -> dict: ...
```

---

#### [NEW] [noaa.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/noaa.py) — NOAA GOES-16/17 + NWS

| Property | Value |
|---|---|
| **NWS API** | `https://api.weather.gov` |
| **GOES S3** | `s3://noaa-goes16/ABI-L2-RRQPE/` |
| **Auth** | Open — requires `User-Agent` header |
| **Format** | GeoJSON (NWS), NetCDF4 (GOES S3) |
| **Rate Limits** | Reasonable use, HTTP 429 on abuse |
| **Libraries** | `requests`, `goes2go`, `xarray`, `s3fs` |

```python
class NOAAConnector(BaseConnector):
    """NOAA weather data: NWS forecasts + GOES-16 satellite rainfall.
    
    Methods:
    - get_alerts(bbox) → list[WeatherAlert]          # NWS active alerts in area
    - get_forecast(lat, lon) → WeatherForecast        # 7-day forecast
    - get_rainfall_qpe(bbox, time) → xr.Dataset       # GOES rainfall rate product
    - get_radar_mosaic(bbox) → GeoJSON                 # MRMS radar
    """
```

---

#### [NEW] [usgs.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/usgs.py) — USGS Water Services

| Property | Value |
|---|---|
| **API** | `https://api.waterdata.usgs.gov/` (new) |
| **Auth** | Free API key recommended (`API_USGS_PAT`) |
| **Format** | JSON, GeoJSON |
| **Rate Limits** | Dynamic, headers `X-RateLimit-Remaining` |
| **Libraries** | `dataretrieval` |

```python
class USGSConnector(BaseConnector):
    """USGS river gauge data: real-time streamflow and water levels.
    
    Methods:
    - get_streamflow(site_id) → GaugeReading           # param 00060
    - get_water_level(site_id) → GaugeReading           # param 00065
    - get_sites_in_bbox(bbox) → list[GaugeSite]         # find gauges in area
    - get_daily_values(site_id, start, end) → DataFrame # historical
    """
```

> [!WARNING]
> Legacy `waterservices.usgs.gov` is being **decommissioned Q1 2027**. This connector targets the new `api.waterdata.usgs.gov` endpoint.

---

#### [NEW] [sentinel_hub.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/sentinel_hub.py) — ESA Copernicus

| Property | Value |
|---|---|
| **Process API** | `https://sh.dataspace.copernicus.eu/api/v1/process` |
| **Catalog** | `https://sh.dataspace.copernicus.eu/api/v1/catalog/` (STAC) |
| **OAuth Token** | `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token` |
| **Auth** | OAuth 2.0 Client Credentials |
| **Format** | GeoTIFF, STAC GeoJSON |
| **Libraries** | `sentinelhub` |

```python
class SentinelHubConnector(BaseConnector):
    """ESA Sentinel-1 SAR + Sentinel-2 optical imagery.
    
    Methods:
    - get_sar_image(bbox, date_range) → GeoTIFF          # Sentinel-1 GRD
    - get_optical_image(bbox, date_range) → GeoTIFF       # Sentinel-2 L2A
    - get_sar_coherence(bbox, date_pair) → float          # dam integrity signal
    - search_catalog(bbox, date_range, collection) → list # STAC search
    - get_flood_extent(bbox, date) → GeoJSON              # water detection
    """
```

---

#### [NEW] [ecmwf.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/ecmwf.py) — ECMWF CDS

| Property | Value |
|---|---|
| **API** | `https://cds.climate.copernicus.eu/api` |
| **Auth** | Personal Access Token in `~/.cdsapirc` |
| **Format** | GRIB, NetCDF |
| **Rate Limits** | Dynamic, 60K items/request max |
| **Libraries** | `cdsapi`, `xarray`, `cfgrib` |

```python
class ECMWFConnector(BaseConnector):
    """ECMWF ensemble weather forecasts for Monte Carlo flood modeling.
    
    Methods:
    - get_ensemble_forecast(bbox, hours_ahead) → xr.Dataset  # 50-member ensemble
    - get_era5_reanalysis(bbox, date_range) → xr.Dataset      # historical baseline
    - get_temperature_humidity(bbox, days) → xr.Dataset        # for DiseaseRiskAgent
    """
```

> [!IMPORTANT]
> Must manually accept Terms of Use for each dataset on the CDS website before API retrieval works.

---

#### [NEW] [soil_moisture.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/soil_moisture.py) — ESA CCI

| Property | Value |
|---|---|
| **CDS dataset** | `satellite-soil-moisture` via `cdsapi` |
| **FTP** | `ftp://anon-ftp.ceda.ac.uk/neodc/esacci/soil_moisture/` |
| **Auth** | Open (FTP) / Token (CDS) |
| **Format** | NetCDF (daily, 0.25° resolution) |
| **Libraries** | `esa_cci_sm`, `cdsapi`, `xarray` |

---

#### [NEW] [glims.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/glims.py) — GLIMS Glacier DB

| Property | Value |
|---|---|
| **WFS** | `https://www.glims.org/geoserver/wfs` |
| **Auth** | Open |
| **Format** | Shapefile, GeoJSON via WFS |
| **Libraries** | `geopandas`, `OWSLib` |

```python
class GLIMSConnector(BaseConnector):
    """GLIMS glacial lake inventory — baseline lake areas, elevations, dam types.
    
    Methods:
    - get_lakes_in_bbox(bbox) → GeoDataFrame             # all lakes in region
    - get_lake_by_id(glims_id) → LakeRecord               # single lake metadata
    - get_lake_area_history(glims_id) → list[AreaRecord]   # area change over time
    """
```

---

#### [NEW] [osm.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/osm.py) — OpenStreetMap

| Property | Value |
|---|---|
| **API** | `https://overpass-api.de/api/interpreter` |
| **Auth** | Open (User-Agent required) |
| **Format** | JSON → GeoJSON |
| **Rate Limits** | ~10K queries/day, ~1GB/day |
| **Libraries** | `osmnx`, `overpy` |

```python
class OSMConnector(BaseConnector):
    """OpenStreetMap: buildings, roads, drainage, shelters.
    
    Methods:
    - get_buildings(bbox) → GeoDataFrame                   # building footprints
    - get_road_network(bbox) → nx.MultiDiGraph             # routable graph
    - get_drainage_network(bbox) → GeoDataFrame            # drains, ditches
    - get_shelters(bbox) → list[Shelter]                   # emergency shelters
    - get_hospitals(bbox) → list[Hospital]                 # medical facilities
    """
```

---

#### [NEW] [worldpop.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/worldpop.py) — WorldPop

| Property | Value |
|---|---|
| **REST API** | `https://api.worldpop.org/v1/services/stats` |
| **Auth** | Open (1K calls/day) |
| **Format** | GeoTIFF (raster), JSON (API) |
| **Libraries** | `worldpoppy`, `rasterio`, `rasterstats` |

---

#### [NEW] [hydrosheds.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/hydrosheds.py) — HydroSHEDS

| Property | Value |
|---|---|
| **Access** | File downloads from `hydrosheds.org` + GEE |
| **Auth** | Open |
| **Format** | Shapefile, GeoTIFF |
| **Libraries** | `geopandas`, `pysheds`, `rasterio` |

```python
class HydroSHEDSConnector(BaseConnector):
    """HydroSHEDS: river networks, watershed boundaries, flow direction DEMs.
    
    Methods:
    - get_river_network(bbox) → GeoDataFrame               # HydroRIVERS
    - get_watershed(lat, lon) → WatershedBoundary           # HydroBASINS
    - get_dem(bbox) → rasterio.DatasetReader                # 90m void-filled DEM
    - get_flow_direction(bbox) → np.ndarray                 # flow routing grid
    """
```

> [!NOTE]
> No REST API — data is pre-downloaded and cached locally. First run downloads required shapefiles (~500MB for global HydroRIVERS). Alternatively uses `mghydro.com` Global Watersheds API for on-demand watershed delineation.

---

#### [NEW] [dartmouth.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/connectors/dartmouth.py) — Dartmouth Flood Observatory

| Property | Value |
|---|---|
| **Access** | `floodobservatory.colorado.edu` + HDX + GEE |
| **Auth** | Open |
| **Format** | CSV/Excel (events), Shapefile (extents) |
| **Libraries** | `pandas`, `geopandas` |

---

### Connector Summary Table

| # | Connector | API Endpoint | Auth | Data Format | Python Library |
|---|-----------|-------------|------|-------------|----------------|
| 1 | NOAA | `api.weather.gov` + `s3://noaa-goes16/` | Open (User-Agent) | GeoJSON, NetCDF4 | `goes2go`, `requests` |
| 2 | USGS | `api.waterdata.usgs.gov` | Free API key | JSON, GeoJSON | `dataretrieval` |
| 3 | Sentinel Hub | `sh.dataspace.copernicus.eu/api/v1/` | OAuth 2.0 | GeoTIFF, STAC | `sentinelhub` |
| 4 | ECMWF | `cds.climate.copernicus.eu/api` | Personal Token | GRIB, NetCDF | `cdsapi` |
| 5 | ESA CCI SM | CEDA FTP / CDS API | Open / Token | NetCDF | `esa_cci_sm`, `xarray` |
| 6 | GLIMS | `glims.org/geoserver/wfs` | Open | GeoJSON | `geopandas`, `OWSLib` |
| 7 | OSM | `overpass-api.de/api/interpreter` | Open | JSON | `osmnx`, `overpy` |
| 8 | WorldPop | `api.worldpop.org/v1/services/stats` | Open (1K/day) | GeoTIFF, JSON | `worldpoppy`, `rasterio` |
| 9 | HydroSHEDS | `hydrosheds.org` (downloads) | Open | Shapefile, GeoTIFF | `geopandas`, `pysheds` |
| 10 | Dartmouth | `floodobservatory.colorado.edu` | Open | CSV, Shapefile | `pandas`, `geopandas` |

---

### Component 2: LLM Reasoning Layer (`backend/floodops/llm/`)

The intelligence that turns raw data into human-understandable decisions.

---

#### [NEW] [client.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/llm/client.py)

```python
class FloodLLMClient:
    """Google Gemini client for flood reasoning.
    
    Uses: google-genai SDK (Gemini 2.5 Flash for speed, Pro for complex analysis)
    
    Capabilities:
    - Structured output (Pydantic models as response schema)
    - Grounding with Google Search (for latest weather news)
    - Function calling (agents can invoke LLM for decisions)
    - Streaming responses (for chat panel)
    """
    
    model_fast: str = "gemini-2.5-flash"   # anomaly interpretation, quick summaries
    model_deep: str = "gemini-2.5-pro"     # complex multi-factor analysis
```

---

#### [NEW] [prompts.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/llm/prompts.py)

System prompts tailored per use case:

```python
ANOMALY_INTERPRETER = """You are a flood hydrology expert analyzing sensor anomalies.
Given: sensor readings, z-scores, baseline statistics, and watershed context.
Produce: a natural-language interpretation explaining WHY this anomaly matters,
what it likely indicates (upstream rainfall, snowmelt, dam failure, etc.),
and what downstream effects to expect. Include confidence level."""

PHASE_TRANSITION_JUSTIFIER = """You are a disaster management decision auditor.
Given: current flood system state, proposed phase transition, and triggering data.
Produce: a structured justification for the audit log explaining why this
transition is warranted, what evidence supports it, and any risks of
false positive/negative."""

SITUATIONAL_REPORT = """You are a flood emergency briefing officer.
Given: complete FloodSystemState with all agent outputs.
Produce: a concise situation report suitable for emergency managers.
Include: affected population, timeline, confidence levels, recommended actions,
and what information is still uncertain."""

CHAT_ASSISTANT = """You are FloodOps AI, an expert assistant for the flood
monitoring system. You can explain what any agent is doing, interpret map
layers, summarize risk data, and answer questions about the current flood
event. You have access to the full system state."""
```

---

#### [NEW] [reasoning.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/llm/reasoning.py)

```python
class FloodReasoner:
    """LLM-powered reasoning integrated into the orchestrator.
    
    Methods:
    - interpret_anomaly(alert: AnomalyAlert, context: WatershedContext) → str
        Called by SentinelAgent when anomaly detected. Produces human-readable
        explanation for the audit log and dashboard.
    
    - justify_transition(from_phase, to_phase, state) → AuditEntry
        Called by Orchestrator before every phase transition. LLM explains
        WHY the transition is justified based on all available evidence.
    
    - generate_sitrep(state: FloodSystemState) → SituationReport
        On-demand situational report for emergency managers.
    
    - chat(message: str, state: FloodSystemState) → AsyncIterator[str]
        Streaming chat interface for the frontend panel.
    
    - analyze_compound_event(alerts: list[AnomalyAlert]) → CompoundAnalysis
        When multiple alerts fire simultaneously, LLM determines if they
        are related (e.g., upstream rain + downstream gauge rise).
    """
```

---

### Component 3: Google OAuth + Workspace (`backend/floodops/auth/`)

---

#### [NEW] [oauth.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/auth/oauth.py)

```python
class GoogleOAuthManager:
    """Google OAuth 2.0 Authorization Code Flow.
    
    Endpoints:
    - Authorization: https://accounts.google.com/o/oauth2/v2/auth
    - Token:         https://oauth2.googleapis.com/token
    - Revocation:    https://oauth2.googleapis.com/revoke
    
    Scopes requested:
    - https://www.googleapis.com/auth/spreadsheets    (Sheets read/write)
    - https://www.googleapis.com/auth/drive.file       (Drive app files)
    - https://www.googleapis.com/auth/gmail.send        (Gmail send only)
    
    Flow:
    1. GET /auth/login → redirect to Google consent screen
    2. GET /auth/callback → exchange code for tokens
    3. Store refresh_token encrypted in local DB
    4. Auto-refresh access_token on expiry
    """
    
    async def get_auth_url(self) -> str: ...
    async def handle_callback(self, code: str) -> TokenPair: ...
    async def refresh_token(self, refresh_token: str) -> str: ...
    async def get_credentials(self) -> Credentials: ...
```

---

#### [NEW] [workspace.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/auth/workspace.py)

```python
class WorkspaceIntegration:
    """Google Workspace integrations for FloodOps.
    
    Sheets (Data Logging):
    - log_sensor_reading(reading: SensorReading) → appends row to 'SensorData' sheet
    - log_phase_transition(event: StateTransitionEvent) → appends to 'PhaseLog' sheet
    - log_alert(alert: AnomalyAlert) → appends to 'Alerts' sheet
    - Auto-creates spreadsheet on first use with formatted headers
    
    Drive (Report Storage):
    - upload_flood_report(report: SituationReport) → PDF in FloodOps/Reports/ folder
    - upload_geojson(name: str, geojson: dict) → stores flood extent GeoJSON
    - list_reports(event_id: str) → all reports for a flood event
    
    Gmail (Alert Emails):
    - send_alert_email(recipients: list[str], alert: AlertPayload) → sends formatted email
    - send_sitrep_email(recipients: list[str], sitrep: SituationReport) → sends report
    """
```

---

### Component 4: Real-Time Google Maps Frontend (`frontend/`)

---

#### [NEW] [index.html](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/index.html)

Main HTML shell with Google Maps script tag, dark theme, and responsive layout:
- Full-viewport map as the primary canvas
- Floating side panel (glassmorphism) for dashboard + layers
- Bottom drawer for LLM chat
- Top bar for phase indicator + auth status

---

#### [NEW] [map.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/map.js)

```javascript
/**
 * Google Maps initialization and management.
 * 
 * Uses:
 * - google.maps.Map — base map (dark theme via Map ID / styled map)
 * - google.maps.Data — GeoJSON flood zone overlays (primary layer system)
 * - google.maps.marker.AdvancedMarkerElement — sensor locations, alerts
 * - google.maps.Polygon — evacuation zones, impact zones
 * - google.maps.ImageMapType — custom raster tiles (flood depth heatmap)
 * 
 * Map ID: Create a styled map in Cloud Console with dark theme for
 * high-contrast flood visualization.
 */

// Initialize with dark-themed map
function initMap() {
    const map = new google.maps.Map(document.getElementById('map'), {
        center: { lat: 27.7, lng: 85.3 },  // Default: Kathmandu (GLOF-prone)
        zoom: 8,
        mapId: 'FLOODOPS_DARK_MAP_ID',      // Styled in Cloud Console
        mapTypeControl: true,
        fullscreenControl: true,
    });
    
    // Initialize all layer systems
    initFloodZoneLayer(map);
    initSensorMarkers(map);
    initEvacuationRoutes(map);
    initHeatmapLayer(map);
}
```

---

#### [NEW] [layers.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/layers.js)

```javascript
/**
 * Map layer management — toggleable overlays for each data type.
 * 
 * Layers:
 * 1. Flood Zones (GeoJSON via Data Layer)
 *    - Color-coded by probability: green (<40%), yellow (40-70%), 
 *      orange (70-90%), red (>90%)
 *    - Click for zone details (population, risk level, drainage gap)
 * 
 * 2. Sensor Stations (AdvancedMarkerElement)
 *    - River gauges (blue), weather stations (gray), SAR coverage (purple)
 *    - Animated pulse when anomaly active
 *    - InfoWindow with real-time reading + z-score
 * 
 * 3. Evacuation Routes (Polyline)
 *    - Green = passable, Red = blocked, Yellow = at risk
 *    - Animated dashes showing direction of evacuation flow
 *    - Shelter markers with capacity indicators
 * 
 * 4. Glacial Lakes (Polygon)
 *    - Color-coded by integrity score: green (>0.7), yellow (0.3-0.7), red (<0.3)
 *    - Click for lake health report
 * 
 * 5. Disease Risk Heatmap (ImageMapType custom tiles)
 *    - Post-flood pathogen risk overlay
 *    - Toggle between cholera / typhoid / leptospirosis
 * 
 * 6. Flood Depth (Custom tile overlay)
 *    - Blue gradient by predicted depth (0.5m–5m+)
 * 
 * All layers fetched from backend /api/v1/map/* endpoints as GeoJSON.
 */
```

---

#### [NEW] [websocket.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/websocket.js)

```javascript
/**
 * WebSocket client for live flood data updates.
 * 
 * Connects to: ws://localhost:8000/ws/flood
 * 
 * Message types received:
 * - phase_transition: { from, to, timestamp, justification }
 * - sensor_update: { sensor_id, value, z_score, anomaly_level }
 * - flood_forecast: { geojson, max_probability, peak_time }
 * - evacuation_update: { routes_geojson, blocked_roads }
 * - alert_dispatch: { level, zones, message }
 * - glof_emergency: { lake_id, impact_zone_geojson, tta_minutes }
 * - disease_risk: { risk_map_geojson, hotspots }
 * - audit_entry: { agent, action, reasoning }
 * 
 * On each message: update corresponding map layer + dashboard panel.
 * Auto-reconnect with exponential backoff on disconnect.
 */
```

---

#### [NEW] [dashboard.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/dashboard.js)

Floating side panel showing:
- Current phase indicator (color-coded, animated on transition)
- Active agents (green dot = running, gray = idle)
- Key metrics: max flood probability, peak time ETA, population at risk
- Recent audit log entries (scrolling feed)
- Layer toggle switches

---

#### [NEW] [chat.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/chat.js)

Bottom drawer with LLM chat interface:
- "Explain what's happening" → streams LLM situational report
- "Why did we escalate to IMMINENT?" → LLM explains transition reasoning
- "What should zone 3 do?" → LLM generates zone-specific advice
- Markdown rendering, typing indicator, message history

---

#### [NEW] [style.css](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/style.css)

Premium dark theme:
- Deep navy background (#0a0f1a) with glassmorphism panels
- Vibrant accent colors matching the agent color scheme from specs
- Smooth transitions on layer toggles and phase changes
- Responsive layout (desktop primary, tablet secondary)
- Custom scrollbars, animated phase indicator dots
- Google Fonts: Inter (UI) + JetBrains Mono (data)

---

### Component 5: FastAPI Backend (`backend/floodops/api/`)

---

#### [NEW] [app.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/app.py)

```python
"""FastAPI application — serves REST API, WebSocket, and OAuth endpoints.

Lifespan:
- On startup: initialize EventBus, register all agents, compile LangGraph,
  connect to external connectors, start CRON schedulers
- On shutdown: gracefully stop CRON jobs, close connector sessions

CORS: configured for frontend origin (localhost:5173 in dev)
"""
```

---

#### [NEW] [routes_map.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_map.py)

```python
"""Map data endpoints — serve GeoJSON for frontend layers.

GET /api/v1/map/flood-zones         → current flood probability GeoJSON
GET /api/v1/map/sensors             → all sensor locations + latest readings
GET /api/v1/map/evacuation-routes   → passable/blocked routes GeoJSON
GET /api/v1/map/glacial-lakes       → lake health polygons GeoJSON
GET /api/v1/map/disease-risk        → disease risk heatmap GeoJSON
GET /api/v1/map/flood-depth         → predicted depth grid GeoJSON
GET /api/v1/map/urban-zones         → zone risk reports GeoJSON
"""
```

---

#### [NEW] [routes_flood.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_flood.py)

```python
"""Flood system endpoints.

GET  /api/v1/flood/state              → current FloodSystemState
GET  /api/v1/flood/phase              → current phase + metadata
GET  /api/v1/flood/audit-log          → paginated audit entries
GET  /api/v1/flood/agents             → agent statuses
POST /api/v1/flood/simulate           → inject mock data for testing
POST /api/v1/flood/chat               → LLM chat (streaming response)
GET  /api/v1/flood/sitrep             → generate situation report
"""
```

---

#### [NEW] [routes_auth.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_auth.py)

```python
"""Google OAuth endpoints.

GET  /auth/login     → redirect to Google consent screen
GET  /auth/callback  → exchange code, store tokens, redirect to app
GET  /auth/status    → check if authenticated
POST /auth/logout    → revoke tokens
"""
```

---

#### [NEW] [websocket.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/websocket.py)

```python
"""WebSocket handler for real-time flood updates.

Endpoint: /ws/flood

Subscribes to EventBus topics and pushes updates to all connected clients.
Each message includes: { type, timestamp, data }

Connection lifecycle:
1. Client connects → send current state snapshot
2. Push updates as agents produce outputs
3. Auto-cleanup on disconnect
"""
```

---

### Component 6: Core System (same as v1, refined)

Data models, event bus, agent skeletons, and LangGraph orchestrator — same structure as the original plan but now wired to real connectors instead of pure mocks. Each agent receives a `connectors` dict at initialization:

```python
# Example: SentinelAgent initialization
sentinel = SentinelAgent(
    event_bus=bus,
    connectors={
        "noaa": noaa_connector,
        "usgs": usgs_connector,
        "sentinel_hub": sentinel_hub_connector,
        "soil_moisture": soil_moisture_connector,
        "glims": glims_connector,
    }
)
```

---

## Connector Setup & Credentials

#### [NEW] [.env.example](file:///c:/Users/hp/Downloads/flood_multi-agent_system/.env.example)

```env
# === Google Cloud ===
GOOGLE_MAPS_API_KEY=your-maps-api-key
GOOGLE_CLIENT_ID=your-oauth-client-id
GOOGLE_CLIENT_SECRET=your-oauth-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# === Google Gemini (LLM) ===
GOOGLE_GENAI_API_KEY=your-gemini-api-key

# === USGS ===
API_USGS_PAT=your-usgs-api-key

# === ESA Copernicus / Sentinel Hub ===
SENTINEL_HUB_CLIENT_ID=your-sh-client-id
SENTINEL_HUB_CLIENT_SECRET=your-sh-client-secret

# === ECMWF CDS ===
ECMWF_CDS_TOKEN=your-cds-personal-access-token

# === Frontend ===
VITE_GOOGLE_MAPS_API_KEY=your-maps-api-key
VITE_WS_URL=ws://localhost:8000/ws/flood
VITE_API_URL=http://localhost:8000/api/v1
```

**Setup steps:**
1. **Google Cloud Console** → Create project → Enable Maps JS API, Sheets API, Drive API, Gmail API
2. **OAuth consent screen** → Configure → Create OAuth Client ID (Web application)
3. **Copernicus Data Space** → Register → Create OAuth credentials
4. **ECMWF CDS** → Register → Get Personal Access Token → Accept dataset Terms of Use
5. **USGS** → Register at `api.waterdata.usgs.gov/signup/` → Get API key
6. **Google AI Studio** → Get Gemini API key

---

## Build Sequence (Updated)

| Step | Layer | What | Files |
|------|-------|------|-------|
| 1 | Setup | `pyproject.toml`, `requirements.txt`, `.env.example`, `config.py` | 4 |
| 2 | Models | All Pydantic models + GeoJSON models | 12 |
| 3 | Queue | Event bus with WebSocket broadcast hook | 2 |
| 4 | Connectors | `BaseConnector` + all 10 data source connectors | 12 |
| 5 | LLM | Gemini client, prompts, reasoning engine | 3 |
| 6 | Auth | OAuth flow + Workspace (Sheets/Drive/Gmail) | 2 |
| 7 | Agents | `BaseAgent` + 7 agent implementations | 8 |
| 8 | Orchestrator | LangGraph graph, nodes, routing | 3 |
| 9 | API | FastAPI app, REST routes, WebSocket handler | 5 |
| 10 | Frontend | Vite app, Maps, layers, WebSocket, dashboard, chat, styles | 10 |
| 11 | Tests | State transitions, connectors, agents, models, auth | 6 |
| 12 | Verify | Run tests, demo scenario, visual verification | — |

**Total: ~65 new files, ~5,000-6,000 lines**

---

## Verification Plan

### Automated Tests

```bash
# Backend tests
cd backend && python -m pytest tests/ -v

# Key test scenarios:
# 1. Full 7-phase state traversal with mock connector data
# 2. Each connector's health_check() passes (requires network)
# 3. Event bus emit/subscribe/direct_call
# 4. Pydantic model validation (probabilities [0,1], coordinates valid)
# 5. OAuth token refresh flow
# 6. WebSocket message broadcast
```

### Manual Verification

1. Run backend (`uvicorn`) + frontend (`npm run dev`)
2. Open browser → Google Maps loads with dark theme
3. Click "Login with Google" → OAuth flow completes
4. Inject mock flood scenario via `/api/v1/flood/simulate`
5. Verify map layers update in real-time via WebSocket
6. Verify phase transitions appear in dashboard
7. Use LLM chat to ask "What's happening?" → get streaming response
8. Verify Sheets log has new rows, Drive has report PDF
