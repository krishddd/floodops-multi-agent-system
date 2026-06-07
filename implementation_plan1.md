# FloodOps v3 — UI-First Implementation Plan

A multi-agent flood orchestration system where the **visualization IS the product**. 3D terrain-aware flood rendering, temporal exploration, ensemble uncertainty, spatial reasoning, and interactive what-if scenarios — powered by 8 agents across 7 phases.

---

## What Changed From v2 (and Why)

The v2 plan was strong engineering with weak UI. This plan inverts the priority:

| Dimension | v2 (What Was Wrong) | v3 (What We're Doing) |
|---|---|---|
| **Dimensional** | Flat 2D Google Maps with color-coded polygons | deck.gl WebGL overlays: extruded flood-depth columns, population hexbins, terrain tilt, arc evacuation flows |
| **Subjective Analysis** | LLM output buried in chat drawer and audit feed | Reasoning surfaced **spatially on the map**: expandable "why" cards per zone/lake, confidence as visual weight, competing hypotheses shown |
| **Dynamism** | Reactive WebSocket repaint — data arrives, layer updates | **Timeline scrubber** with event replay + forecast animation; **what-if scenarios** with draggable parameters |
| **Real-World Usefulness** | 50-member ensemble collapsed to single "max probability" gauge | **Ensemble disagreement visualization**: spaghetti plots, probability fans, "10% catastrophic / 60% moderate" shown explicitly |
| **Connectors** | 10 heterogeneous sources (days of integration each) | **4 live** (USGS, NWS, ECMWF, OSM) + **6 mocked** behind same interface — reinvest saved effort into UI |
| **"Real-time" honesty** | 30s WebSocket poll implying everything is live | Explicit data-cadence badges per layer; dynamism from **modeling and interaction**, not polling cadence |

**Effort allocation:**
- Frontend visualization: **~60%**
- Backend (agents, orchestrator, LLM): **~25%**
- Connectors + auth: **~15%**

---

## User Review Required

> [!IMPORTANT]
> **deck.gl + Google Maps**: This plan uses [deck.gl's GoogleMapsOverlay](https://deck.gl/docs/api-reference/google-maps/google-maps-overlay) to render WebGL layers on top of Google Maps. This gives us true 3D (extruded columns, terrain, arcs) while keeping Google's base map, search, and satellite imagery. Requires `@deck.gl/google-maps` npm package.

> [!WARNING]
> **Google Photorealistic 3D Tiles**: For mountain/valley terrain (Kathmandu, GLOF scenarios), Google's 3D Tiles API provides photorealistic terrain. This is a separate Maps Platform SKU with its own pricing. Do you want this enabled, or is deck.gl terrain-layer sufficient?

> [!IMPORTANT]
> **Connector cut**: Only 4 connectors will fetch real data (USGS gauges, NWS alerts/radar, ECMWF ensemble, OSM roads/buildings). The other 6 (Sentinel Hub, Soil Moisture, GLIMS, WorldPop, HydroSHEDS, Dartmouth) return realistic mock data from the same `BaseConnector` interface — swappable to real APIs later without changing any agent code.

## Open Questions

1. **deck.gl vs Cesium/MapboxGL**: deck.gl on Google Maps is the recommended approach. Alternative: Mapbox GL JS with Mapbox terrain (no Google dependency). Preference?

2. **Ensemble member count for visualization**: ECMWF provides 50 members. Rendering all 50 as spaghetti lines may be noisy — should we show top 10 representative members + probability fan, or all 50?

3. **Timeline range**: How far back should the scrubber go for historical replay? Plan assumes 7 days of history + 10 days forecast.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     FRONTEND  (Vite + deck.gl + Google Maps)            │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                    3D MAP CANVAS (full viewport)                    │  │
│  │                                                                    │  │
│  │  deck.gl GoogleMapsOverlay                                         │  │
│  │  ├─ GeoJsonLayer (flood zones, risk-colored, opacity=confidence)  │  │
│  │  ├─ ColumnLayer  (extruded flood depth per 30m cell)              │  │
│  │  ├─ HexagonLayer (population-at-risk density)                     │  │
│  │  ├─ ArcLayer     (evacuation flows: origin→shelter)               │  │
│  │  ├─ PathLayer    (ensemble spaghetti: flood-front trajectories)   │  │
│  │  ├─ ScatterplotLayer (sensors: gauges, weather stations)          │  │
│  │  └─ PolygonLayer (glacial lakes, colored by integrity)            │  │
│  │                                                                    │  │
│  │  Google Maps base: dark styled map + terrain tilt (ctrl+drag)     │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────┐ ┌──────────────────────────┐ ┌──────────────────────┐ │
│  │ LAYER PANEL  │ │ TIMELINE SCRUBBER         │ │ SPATIAL "WHY" CARDS │ │
│  │ Toggle + α   │ │ ◄──●────────────────────► │ │ Attached to zones   │ │
│  │ per layer    │ │ T-72h ··· NOW ··· T+10d   │ │ LLM reasoning      │ │
│  │              │ │ ▶ Play  ⏸ Pause  1x/4x   │ │ + confidence bars   │ │
│  └──────────────┘ └──────────────────────────┘ └──────────────────────┘ │
│                                                                          │
│  ┌──────────────────────────┐  ┌─────────────────────────────────────┐  │
│  │ WHAT-IF SCENARIO PANEL   │  │ ENSEMBLE UNCERTAINTY PANEL          │  │
│  │ ┌─ Rainfall: ████░░ 120mm│  │ Probability fan (5th–95th pctile)  │  │
│  │ ├─ Dam break: T+__h      │  │ Spaghetti: 10 representative mbrs  │  │
│  │ ├─ Soil sat:  ████░ 80%  │  │ "40% agree: catastrophic"          │  │
│  │ └─ [Re-run forecast]     │  │ "55% agree: moderate flooding"     │  │
│  └──────────────────────────┘  └─────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────────┐│
│  │ PHASE BAR:  ●00 Monitor  ○01 Elevated  ○02 Imminent  ...          ││
│  │ DATA CADENCE: 🟢 USGS 15min  🟢 NWS 15min  🟡 SAR ~6d  ⚪ Mock   ││
│  └──────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────┘
         ▲ WebSocket (state changes, forecast frames, sensor ticks)
         │
┌────────┼─────────────────────────────────────────────────────────────────┐
│        ▼                                                                 │
│  BACKEND (FastAPI + LangGraph + Gemini)                                 │
│  ├─ /ws/flood           WebSocket: push state + forecast frames          │
│  ├─ /api/v1/map/*       GeoJSON endpoints (flood, sensors, routes...)   │
│  ├─ /api/v1/flood/*     State, audit, simulate, chat, sitrep            │
│  ├─ /api/v1/scenario/*  What-if: re-run forecast with modified params   │
│  ├─ /api/v1/ensemble/*  Ensemble members, probability fan data          │
│  ├─ /api/v1/timeline/*  Historical frames for scrubber playback         │
│  ├─ /auth/*             Google OAuth 2.0                                 │
│  │                                                                       │
│  ├─ Orchestrator (LangGraph 7-phase state machine)                      │
│  ├─ 8 Agents (Sentinel, GLOF, Predict, Urban, Alert, Resource, Disease) │
│  ├─ LLM Reasoning (Gemini: spatial "why" cards, transition justification)│
│  ├─ 4 Live Connectors (USGS, NWS, ECMWF, OSM)                         │
│  └─ 6 Mock Connectors (SentinelHub, SoilMoisture, GLIMS, WorldPop,     │
│                         HydroSHEDS, Dartmouth) — same interface          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
flood_multi-agent_system/
├── flood_agent_specs.jsx                    # [EXISTING]
├── flood_multiagent_orchestration.html      # [EXISTING]
│
├── frontend/                                # [NEW] ★ PRIMARY EFFORT ★
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   ├── src/
│   │   ├── main.js                          # App bootstrap
│   │   │
│   │   ├── map/                             # ★ 3D Map Engine
│   │   │   ├── init.js                      # Google Maps + deck.gl overlay setup
│   │   │   ├── layers.js                    # All deck.gl layer definitions
│   │   │   ├── terrain.js                   # Terrain tilt + 3D tiles config
│   │   │   └── interactions.js              # Click → "why" card, hover → tooltip
│   │   │
│   │   ├── timeline/                        # ★ Temporal Exploration
│   │   │   ├── scrubber.js                  # Timeline slider + playback controls
│   │   │   ├── animator.js                  # Frame-by-frame forecast animation
│   │   │   └── keyframes.js                 # Interpolation between forecast snapshots
│   │   │
│   │   ├── ensemble/                        # ★ Uncertainty Visualization
│   │   │   ├── spaghetti.js                 # Ensemble member path rendering
│   │   │   ├── probability-fan.js           # 5th–95th percentile fan chart
│   │   │   ├── disagreement.js              # "X% agree catastrophic" badges
│   │   │   └── member-selector.js           # Toggle individual ensemble members
│   │   │
│   │   ├── reasoning/                       # ★ Spatial LLM Reasoning
│   │   │   ├── why-cards.js                 # Expandable cards attached to map features
│   │   │   ├── confidence-renderer.js       # Opacity/border/glow = confidence level
│   │   │   ├── hypotheses.js                # Show competing explanations per zone
│   │   │   └── chat.js                      # LLM chat drawer (secondary to spatial)
│   │   │
│   │   ├── scenarios/                       # ★ What-If Explorer
│   │   │   ├── scenario-panel.js            # Parameter sliders (rainfall, dam-break, etc.)
│   │   │   ├── diff-renderer.js             # Before/after comparison overlay
│   │   │   └── scenario-api.js              # Calls /api/v1/scenario/*
│   │   │
│   │   ├── panels/                          # UI Chrome
│   │   │   ├── layer-panel.js               # Layer toggles + opacity sliders + cadence badges
│   │   │   ├── phase-bar.js                 # Phase indicator strip
│   │   │   ├── metrics.js                   # Key numbers (pop at risk, peak ETA, etc.)
│   │   │   └── data-cadence.js              # Honest "last updated" per source
│   │   │
│   │   ├── auth.js                          # Google OAuth login
│   │   ├── websocket.js                     # WebSocket client + reconnect
│   │   ├── state.js                         # Client-side state management
│   │   └── style.css                        # Full design system
│   │
│   └── public/
│       └── favicon.svg
│
├── backend/                                 # [NEW]
│   ├── pyproject.toml
│   ├── requirements.txt
│   │
│   ├── floodops/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   │
│   │   ├── models/                          # Pydantic models (same as v2)
│   │   │   ├── __init__.py
│   │   │   ├── enums.py
│   │   │   ├── state.py                     # FloodSystemState
│   │   │   ├── sentinel.py
│   │   │   ├── glof.py
│   │   │   ├── predict.py                   # + EnsembleMember, ProbabilityFan
│   │   │   ├── urban.py
│   │   │   ├── alert.py
│   │   │   ├── resource.py
│   │   │   ├── disease.py
│   │   │   ├── orchestrator.py
│   │   │   ├── geo.py                       # GeoJSON, BBox, Coordinate
│   │   │   └── scenario.py                  # [NEW] ScenarioParams, ScenarioResult
│   │   │
│   │   ├── queue/
│   │   │   ├── __init__.py
│   │   │   └── event_bus.py
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── sentinel.py
│   │   │   ├── glof.py
│   │   │   ├── predict.py
│   │   │   ├── urban.py
│   │   │   ├── alert.py
│   │   │   ├── resource.py
│   │   │   └── disease.py
│   │   │
│   │   ├── orchestrator/
│   │   │   ├── __init__.py
│   │   │   ├── graph.py
│   │   │   ├── nodes.py
│   │   │   └── routing.py
│   │   │
│   │   ├── connectors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                      # BaseConnector (rate limit, retry, cache)
│   │   │   ├── noaa.py                      # 🟢 LIVE — NWS alerts + GOES rainfall
│   │   │   ├── usgs.py                      # 🟢 LIVE — river gauges (15-min)
│   │   │   ├── ecmwf.py                     # 🟢 LIVE — ensemble forecasts
│   │   │   ├── osm.py                       # 🟢 LIVE — roads, buildings, drainage
│   │   │   ├── sentinel_hub.py              # ⚪ MOCK — returns realistic SAR stubs
│   │   │   ├── soil_moisture.py             # ⚪ MOCK
│   │   │   ├── glims.py                     # ⚪ MOCK — static lake inventory
│   │   │   ├── worldpop.py                  # ⚪ MOCK — synthetic population grids
│   │   │   ├── hydrosheds.py                # ⚪ MOCK — cached watershed data
│   │   │   └── dartmouth.py                 # ⚪ MOCK — historical event stubs
│   │   │
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── client.py                    # Gemini client
│   │   │   ├── prompts.py                   # Data-grounded prompts (not generic)
│   │   │   └── reasoning.py                 # Spatial "why" cards, hypotheses
│   │   │
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── oauth.py
│   │   │   └── workspace.py                 # Sheets, Drive, Gmail
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── app.py                       # FastAPI app
│   │   │   ├── routes_flood.py
│   │   │   ├── routes_map.py                # GeoJSON for all layers
│   │   │   ├── routes_auth.py
│   │   │   ├── routes_scenario.py           # [NEW] What-if scenario endpoints
│   │   │   ├── routes_ensemble.py           # [NEW] Ensemble member data
│   │   │   ├── routes_timeline.py           # [NEW] Historical frame endpoints
│   │   │   └── websocket.py
│   │   │
│   │   └── main.py
│   │
│   └── tests/
│       ├── test_state_transitions.py
│       ├── test_event_bus.py
│       ├── test_agents.py
│       ├── test_connectors.py
│       └── test_models.py
│
├── .env.example
└── docker-compose.yml
```

---

## Proposed Changes

### ★ Component 1: 3D Map Engine (`frontend/src/map/`)

The centerpiece. Everything else serves this.

---

#### [NEW] [init.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/map/init.js)

```javascript
/**
 * Google Maps + deck.gl initialization.
 * 
 * Stack:
 * - Google Maps JavaScript API (base map, satellite imagery, search)
 * - deck.gl GoogleMapsOverlay (WebGL layers on top)
 * - Google Maps styled with dark theme via Cloud-based Map Styling
 * 
 * Camera defaults:
 * - Center: configurable per deployment (Kathmandu for GLOF, Houston for flash flood)
 * - Tilt: 45° (shows terrain depth — critical for mountain/valley flooding)
 * - Heading: 0° (north up, user-rotatable via ctrl+drag)
 * 
 * The map is ALWAYS tilted by default. Flat overhead view hides the
 * entire point of flood depth and valley topography.
 */

import { GoogleMapsOverlay } from '@deck.gl/google-maps';
import { buildLayers } from './layers.js';

export function initMap(container, config) {
    const map = new google.maps.Map(container, {
        center: config.center,
        zoom: config.zoom,
        tilt: 45,                    // ← 3D tilt ON by default
        heading: 0,
        mapId: config.mapId,         // dark styled map
        mapTypeId: 'hybrid',         // satellite + labels
        mapTypeControl: true,
        fullscreenControl: true,
        rotateControl: true,
        tiltControl: true,
    });

    const overlay = new GoogleMapsOverlay({ layers: [] });
    overlay.setMap(map);

    return { map, overlay };
}
```

---

#### [NEW] [layers.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/map/layers.js)

The core visual system. Each layer maps to a specific data type and a specific deck.gl layer class chosen for maximum visual impact:

```javascript
/**
 * deck.gl layer definitions for FloodOps.
 * 
 * LAYER ARCHITECTURE (bottom to top rendering order):
 * 
 * 1. FLOOD ZONES — GeoJsonLayer
 *    Source: /api/v1/map/flood-zones
 *    Rendering: polygon fill color = risk level, 
 *               fill OPACITY = LLM confidence score (0.2–0.9)
 *               stroke WEIGHT = number of agreeing ensemble members
 *    This means: bright solid red = high risk + high confidence + high agreement
 *                faint transparent orange = moderate risk + uncertain + members disagree
 *    Click: opens spatial "why" card with LLM reasoning
 * 
 * 2. FLOOD DEPTH — ColumnLayer (extruded 3D)
 *    Source: /api/v1/map/flood-depth
 *    Rendering: 30m grid cells extruded to predicted water depth
 *               Color: blue gradient by depth (0.5m cyan → 5m+ dark navy)
 *               Height: actual depth value (1m of water = 1m extrusion)
 *    WHY 3D: Flood depth is literally a 3rd dimension. A flat heatmap
 *    hides the single most life-critical variable. Extruded columns
 *    on a tilted map make depth viscerally obvious.
 * 
 * 3. POPULATION AT RISK — HexagonLayer (aggregated 3D hexbins)
 *    Source: /api/v1/map/population-risk
 *    Rendering: hexagonal bins, height = population count, 
 *               color = risk score (green → red)
 *    WHY HEXBINS: shows WHERE people are vs WHERE water is going.
 *    A tall red hexbin next to a deep blue column = urgent evacuation.
 * 
 * 4. EVACUATION FLOWS — ArcLayer (3D arcs)
 *    Source: /api/v1/map/evacuation-routes
 *    Rendering: curved 3D arcs from risk zones to shelters
 *               Color: source=red (danger), target=green (shelter)
 *               Width: proportional to population being routed
 *               Animated: pulse animation along arc direction
 *    WHY ARCS (not polylines): arcs show the FLOW of people,
 *    not just the road. You see movement, direction, and volume.
 * 
 * 5. ENSEMBLE SPAGHETTI — PathLayer
 *    Source: /api/v1/ensemble/members
 *    Rendering: each ensemble member's predicted flood-front boundary
 *               as a thin semi-transparent line. 50 overlapping lines
 *               naturally form a "probability density" — thick where
 *               members agree, wispy where they disagree.
 *    Toggle: individual members selectable via member-selector panel
 * 
 * 6. SENSORS — ScatterplotLayer
 *    Source: /api/v1/map/sensors
 *    Rendering: circles at gauge/station locations
 *               Size: pulsing animation when anomaly active
 *               Color: blue=normal, yellow=elevated, red=critical
 *               Ring: outer ring opacity = data freshness
 *                     (solid = <15min old, fading = stale)
 *    Data cadence badge: "🟢 15min" / "🟡 6-day" shown on hover
 * 
 * 7. GLACIAL LAKES — PolygonLayer (with extrusion)
 *    Source: /api/v1/map/glacial-lakes
 *    Rendering: lake polygons extruded by volume (taller = more water)
 *               Fill color by integrity score:
 *               green (>0.7) → yellow (0.3–0.7) → red (<0.3)
 *               Red pulsing glow when integrity < 0.3 (breach imminent)
 *    Click: lake health report + LLM "why" card with breach scenario
 */
```

---

#### [NEW] [terrain.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/map/terrain.js)

```javascript
/**
 * Terrain configuration for mountain/valley flood visualization.
 * 
 * For GLOF scenarios (Kathmandu valley, Himalayan glacial lakes),
 * terrain is the entire story. Water flows downhill through valleys
 * and the topography determines everything.
 * 
 * Options (user configurable):
 * 1. Google Maps terrain tilt (built-in, free) — tilted 2.5D view
 *    showing terrain shading. Good enough for most cases.
 * 
 * 2. Google Photorealistic 3D Tiles (premium) — actual 3D mesh of
 *    mountains, buildings, rivers. Stunning but costs per tile load.
 *    Enabled via: map.setMapTypeId('photorealistic3d')
 * 
 * 3. deck.gl TerrainLayer — renders DEM elevation data as a 3D mesh
 *    with the map texture draped on top. Uses Mapbox Terrain-RGB tiles
 *    (free tier: 200k tiles/month). Good middle ground.
 */
```

---

#### [NEW] [interactions.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/map/interactions.js)

```javascript
/**
 * Map interaction handlers.
 * 
 * Click on ANY map feature → opens a spatial "why" card:
 * 
 * ┌─────────────────────────────────────────┐
 * │ Zone 3 — Kirtipur Ward                  │  ← zone name
 * │ Risk: ████████░░ HIGH (0.82)            │  ← colored bar
 * │                                          │
 * │ WHY THIS RISK LEVEL:                     │  ← LLM reasoning
 * │ "Upstream gauge at Bagmati (USGS-1234)   │
 * │  shows 3.2σ deviation. Combined with     │
 * │  85% soil saturation, 38 of 50 ensemble  │
 * │  members predict >1m depth here within   │
 * │  18 hours."                              │
 * │                                          │
 * │ CONFIDENCE: ████████░░ 76%               │  ← visual bar
 * │ ENSEMBLE AGREEMENT: 38/50 members        │
 * │                                          │
 * │ COMPETING VIEW (12 members):             │  ← not collapsed!
 * │ "If rainfall shifts 20km east (as 12     │
 * │  members project), this zone sees only   │
 * │  minor flooding (0.3m)."                 │
 * │                                          │
 * │ ▶ Population: 12,400                     │
 * │ ▶ Nearest shelter: 1.2km (Kirtipur HS)  │
 * │ ▶ Drainage gap: 45mm (built for 100yr,  │
 * │   current event is 250yr equivalent)     │
 * ├─────────────────────────────────────────┤
 * │ Data: USGS 🟢 12min ago │ ECMWF 🟢 2h  │  ← cadence badges
 * └─────────────────────────────────────────┘
 * 
 * The card does NOT just narrate. It:
 * - Shows actual numbers from actual sensors
 * - Quantifies confidence with a bar, not just a word
 * - Shows what the DISSENTING ensemble members think
 * - Badges the freshness of each data source
 */
```

---

### ★ Component 2: Timeline & Temporal Exploration (`frontend/src/timeline/`)

The single most impactful addition. Flooding is a process, not a snapshot.

---

#### [NEW] [scrubber.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/timeline/scrubber.js)

```javascript
/**
 * Timeline scrubber for event replay and forecast exploration.
 * 
 * ◄──────●────────────────────────────────────────►
 * T-72h    T-48h    T-24h    NOW    T+24h    T+10d
 *                              ▲
 *          ▶ Play   ⏸ Pause   1x  2x  4x
 * 
 * BEHAVIOR:
 * - Drag left of NOW: REPLAY mode
 *   Shows historical sensor readings, past forecasts, actual flood extent.
 *   Layers animate to show how the event developed.
 *   Audit log entries appear at the time they were generated.
 * 
 * - Drag right of NOW: FORECAST mode
 *   Shows ensemble prediction for future hours.
 *   Flood zones expand/contract based on forecast.
 *   Ensemble spread widens further into the future (uncertainty grows).
 *   Population-at-risk hexbins update per time step.
 * 
 * - Press PLAY: auto-animate through all frames at 1x/2x/4x speed.
 *   Like watching the flood happen in fast-forward.
 * 
 * DATA SOURCE:
 * - Backend stores forecast snapshots as "frames" (one per hour)
 * - GET /api/v1/timeline/frames?start=T-72h&end=T+10d&step=1h
 * - Returns array of GeoJSON snapshots, one per time step
 * - Frontend interpolates between frames for smooth animation
 * 
 * PHASE MARKERS:
 * - Colored dots on the timeline show when phase transitions occurred
 * - Hovering a dot shows the LLM transition justification
 */
```

---

#### [NEW] [animator.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/timeline/animator.js)

```javascript
/**
 * Frame-by-frame animation engine.
 * 
 * Manages the animation loop:
 * 1. Pre-fetches frames from /api/v1/timeline/frames in chunks
 * 2. Interpolates between keyframes for smooth 60fps transitions
 * 3. Updates ALL layers simultaneously per frame:
 *    - Flood depth columns grow/shrink
 *    - Flood zone polygons expand/contract
 *    - Population hexbins update counts
 *    - Evacuation arcs appear/disappear as routes change
 *    - Sensor markers pulse on anomaly frames
 *    - Ensemble spaghetti lines converge (near NOW) or diverge (future)
 * 4. Fires events for dashboard metrics to update (pop at risk, etc.)
 * 
 * Performance:
 * - Uses requestAnimationFrame for smooth rendering
 * - Transitions via deck.gl's built-in layer transition system
 * - Keyframe data is lightweight GeoJSON (only changed cells per frame)
 */
```

---

#### [NEW] [keyframes.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/timeline/keyframes.js)

```javascript
/**
 * Keyframe interpolation between forecast snapshots.
 * 
 * Backend provides hourly snapshots. Frontend interpolates to 60fps:
 * - Flood depth: linear interpolation between cell values
 * - Flood extent: polygon morphing (expand/contract boundaries)
 * - Evacuation routes: fade in/out as roads become blocked/passable
 * - Population at risk: smooth count transitions
 * 
 * Uses deck.gl layer transitions:
 *   new ColumnLayer({
 *     transitions: { getElevation: 800 },  // 800ms smooth height transition
 *     ...
 *   })
 */
```

---

### ★ Component 3: Ensemble Uncertainty Visualization (`frontend/src/ensemble/`)

Your ECMWF 50-member ensemble is a gift. This component makes the disagreement visible.

---

#### [NEW] [spaghetti.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/ensemble/spaghetti.js)

```javascript
/**
 * Ensemble spaghetti plot rendered ON the map.
 * 
 * Each ensemble member produces a predicted flood-front boundary at T+N hours.
 * Render all of them as semi-transparent PathLayer lines:
 * 
 * - Where members agree → lines stack → area appears solid/opaque
 * - Where members disagree → lines scatter → area appears wispy/uncertain
 * 
 * This is the most natural uncertainty visualization because it maps
 * directly to the map space. You can SEE where the forecast is confident
 * vs where it's uncertain, geographically.
 * 
 * Rendering:
 * - 10 "representative" members (selected by k-means clustering of outcomes)
 * - Each line: 2px wide, 20% opacity, distinct hue from a 10-color palette
 * - All 50 can be toggled on (noisy but honest)
 * - Lines animate forward with the timeline scrubber
 * 
 * Source: GET /api/v1/ensemble/members?time=T+24h
 * Returns: { members: [{ id: 1, flood_front: GeoJSON_LineString }, ...] }
 */
```

---

#### [NEW] [probability-fan.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/ensemble/probability-fan.js)

```javascript
/**
 * Probability fan chart — side panel visualization.
 * 
 * For a selected point on the map (click any location):
 * Shows the range of predicted flood depth at that point over time.
 * 
 *    Depth(m)
 *    5 │          ╱‾‾‾‾‾‾‾╲        ← 95th percentile (worst case)
 *    4 │        ╱            ╲
 *    3 │      ╱   ████████     ╲   ← 75th percentile
 *    2 │    ╱  ██████████████    ╲ ← median
 *    1 │  ╱ ████████████████████  ╲← 25th percentile
 *    0 │╱───────────────────────────← 5th percentile (best case)
 *      └──────────────────────────── Time
 *       NOW  +6h  +12h  +24h  +48h
 * 
 * The FAN WIDTH is the uncertainty. Narrow fan = confident. Wide fan = uncertain.
 * This is the single best way to communicate "we're not sure" to a decision-maker.
 * 
 * Rendered using HTML Canvas (not deck.gl — it's a 2D chart).
 * Updates when: (a) user clicks new map point, (b) timeline scrubber moves.
 */
```

---

#### [NEW] [disagreement.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/ensemble/disagreement.js)

```javascript
/**
 * Ensemble disagreement badges — overlaid on flood zone features.
 * 
 * Per zone, show a human-readable summary of what ensemble members think:
 * 
 *   ┌─────────────────────────────────┐
 *   │ 🔴 40% of members: catastrophic │  (>3m depth)
 *   │ 🟠 35% of members: severe       │  (1-3m depth)
 *   │ 🟡 20% of members: moderate     │  (0.5-1m depth)
 *   │ 🟢  5% of members: minimal      │  (<0.5m depth)
 *   └─────────────────────────────────┘
 * 
 * This is the "real-world subjective usefulness" — a decision-maker
 * can see that the forecast is CONTESTED, not settled, and plan for
 * the 40% catastrophic scenario without assuming it's certain.
 * 
 * Positioned as floating badges near zone centroids on the map.
 * Only shown for zones with high disagreement (std dev of member
 * outcomes > threshold).
 */
```

---

### ★ Component 4: What-If Scenario Explorer (`frontend/src/scenarios/`)

---

#### [NEW] [scenario-panel.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/scenarios/scenario-panel.js)

```javascript
/**
 * Interactive parameter sliders for what-if exploration.
 * 
 * ┌─ WHAT-IF SCENARIO ──────────────────────────┐
 * │                                               │
 * │ Rainfall intensity:                           │
 * │ ──────────●────────── 120mm/24h (current)     │
 * │                                               │
 * │ Rainfall shift (east/west):                   │
 * │ ──────●──────────── -10km (shift west)        │
 * │                                               │
 * │ Soil saturation override:                     │
 * │ ──────────────●──── 85% (current)             │
 * │                                               │
 * │ Dam break time (GLOF):                        │
 * │ ──────────●──────── T+6h from now             │
 * │                                               │
 * │ ┌─────────────────────────────────┐           │
 * │ │  ▶ RE-RUN FORECAST              │           │
 * │ └─────────────────────────────────┘           │
 * │                                               │
 * │ Comparing: CURRENT vs SCENARIO                │
 * │ ΔPopulation at risk: +4,200                   │
 * │ ΔPeak depth zone 3:  +1.8m                    │
 * │ ΔPeak time:          -3 hours (earlier)       │
 * └───────────────────────────────────────────────┘
 * 
 * FLOW:
 * 1. User adjusts sliders
 * 2. Click "Re-run forecast" → POST /api/v1/scenario/run
 * 3. Backend re-runs FloodPredictAgent with modified parameters
 * 4. Returns diff GeoJSON (current vs scenario)
 * 5. diff-renderer.js shows side-by-side or overlay comparison
 * 
 * This is where dynamism becomes EXPLORATION, not just reaction.
 */
```

---

#### [NEW] [diff-renderer.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/scenarios/diff-renderer.js)

```javascript
/**
 * Before/after scenario comparison on the map.
 * 
 * Two modes:
 * 
 * 1. SPLIT VIEW: vertical divider, left=current right=scenario
 *    User drags divider to compare. Classic "swipe" comparison.
 * 
 * 2. OVERLAY: scenario rendered as dashed outlines over current solid fills
 *    Green dashed = scenario has LESS flooding than current (good news)
 *    Red dashed = scenario has MORE flooding (worse outcome)
 *    This makes the delta immediately visible without losing context.
 * 
 * Both modes update live as the timeline scrubber moves.
 */
```

---

### ★ Component 5: Spatial LLM Reasoning (`frontend/src/reasoning/`)

LLM output belongs ON the map, not in a chat drawer.

---

#### [NEW] [why-cards.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/reasoning/why-cards.js)

```javascript
/**
 * Expandable "why" cards attached to map features.
 * 
 * Every zone, lake, and sensor on the map can be clicked to see WHY
 * the system assigned its current risk level. The card contains:
 * 
 * 1. LLM-generated natural language explanation
 *    - Grounded in actual numbers ("gauge USGS-1234 reads 4.2m, which is 3.2σ")
 *    - Explicitly states uncertainty ("38 of 50 members agree")
 *    - References specific data sources with cadence badges
 * 
 * 2. Confidence bar (visual, not just a number)
 *    - Maps to fill opacity on the zone polygon
 *    - Low confidence = transparent zone, high = solid
 * 
 * 3. Competing hypotheses (when ensemble disagrees)
 *    - "MAJORITY VIEW (38 members): severe flooding..."
 *    - "MINORITY VIEW (12 members): rainfall shifts east..."
 *    - Both shown. Decision-maker sees the disagreement.
 * 
 * 4. Data provenance
 *    - Which sensors/sources contributed to this assessment
 *    - Freshness badge per source (🟢 <15min, 🟡 <1hr, 🔴 stale)
 * 
 * Cards are positioned near the clicked feature using a smart
 * anchor that avoids overlapping other cards or the edge of screen.
 * 
 * Source: GET /api/v1/flood/reasoning?zone_id=X
 * Backend calls Gemini with the zone's actual data (not generic prompt).
 */
```

---

#### [NEW] [confidence-renderer.js](file:///c:/Users/hp/Downloads/flood_multi-agent_system/frontend/src/reasoning/confidence-renderer.js)

```javascript
/**
 * Confidence as visual weight on map features.
 * 
 * Instead of just coloring by risk level, map features encode TWO dimensions:
 * 
 *   COLOR  = risk level    (green → yellow → orange → red)
 *   OPACITY = confidence   (0.2 = very uncertain → 0.9 = very confident)
 *   STROKE = agreement     (thin = few members agree → thick = many agree)
 *   GLOW   = data freshness (bright glow = fresh data → no glow = stale)
 * 
 * Result: A bright, solid, thick-bordered red zone = URGENT + CERTAIN
 *         A faint, transparent, thin-bordered orange zone = CONCERNING + UNCERTAIN
 * 
 * This is subtle but critical. Without it, a 90% confident "moderate risk"
 * and a 30% confident "high risk" look the same. With it, the uncertain
 * one is visually weaker, which is exactly right for decision-making.
 */
```

---

### Component 6: Revised LLM Prompts (`backend/floodops/llm/prompts.py`)

v2 prompts were generic ("You are a flood hydrology expert…"). v3 prompts are **data-grounded** and **uncertainty-forced**.

---

#### [NEW] [prompts.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/llm/prompts.py)

```python
SPATIAL_REASONING = """You are generating a risk explanation for zone {zone_id} ({zone_name}).

ACTUAL DATA (do not invent numbers — use only these):
- Upstream gauge {gauge_id}: {gauge_value}m ({z_score}σ deviation, last reading {minutes_ago}min ago)
- Soil saturation: {soil_pct}% (source: {soil_source}, last update: {soil_age})
- ECMWF ensemble: {n_members_flood}/{total_members} members predict >{depth_threshold}m depth
- Current phase: {current_phase}, entered {phase_duration} ago

RULES:
1. Cite specific numbers. Never say "high rainfall" — say "142mm in 24h, which is 2.8σ above the 30-day mean."
2. Quantify confidence as a fraction: "38 of 50 ensemble members agree."
3. If members disagree, SHOW BOTH VIEWS. Explain what the minority members see differently.
4. State what data is MISSING or STALE. If SAR data is 4 days old, say so.
5. Express genuine uncertainty. If the forecast could go either way, say "This is a close call because..."
6. Do not use words like "catastrophic" unless >80% of members support that outcome.
"""

TRANSITION_JUSTIFICATION = """Justify the phase transition from {from_phase} to {to_phase}.

TRIGGERING DATA:
{trigger_data_json}

GATE CONDITIONS:
{gate_conditions_json}

RULES:
1. Be specific: "FloodPredictAgent reports max probability 0.83, exceeding the 0.70 threshold."
2. Acknowledge what could make this a false alarm.
3. State what would need to happen for de-escalation.
4. If any gate condition was borderline, flag it explicitly.
"""
```

---

### Component 7: Backend API — New Endpoints

---

#### [NEW] [routes_scenario.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_scenario.py)

```python
"""What-if scenario endpoints.

POST /api/v1/scenario/run
  Body: { rainfall_mm: 120, soil_saturation: 0.85, dam_break_time_h: null, rainfall_shift_km: 0 }
  → Re-runs FloodPredictAgent with modified parameters
  → Returns: { current: GeoJSON, scenario: GeoJSON, diff: { delta_pop, delta_depth, delta_peak_time } }

GET /api/v1/scenario/presets
  → Built-in scenarios: "worst case", "best case", "GLOF breach", "climate +2°C rainfall"
"""
```

---

#### [NEW] [routes_ensemble.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_ensemble.py)

```python
"""Ensemble data endpoints.

GET /api/v1/ensemble/members?time=T+24h
  → Returns all ensemble member flood-front boundaries as GeoJSON LineStrings

GET /api/v1/ensemble/fan?lat=27.7&lng=85.3
  → Returns probability fan data for a map point:
    { percentiles: { p5: [...], p25: [...], p50: [...], p75: [...], p95: [...] },
      time_steps: ["T+0h", "T+6h", ...] }

GET /api/v1/ensemble/disagreement?zone_id=3
  → Returns: { catastrophic_pct: 0.40, severe_pct: 0.35, moderate_pct: 0.20, minimal_pct: 0.05 }

GET /api/v1/ensemble/representatives?n=10
  → Returns 10 k-means-clustered representative members (for spaghetti plot)
"""
```

---

#### [NEW] [routes_timeline.py](file:///c:/Users/hp/Downloads/flood_multi-agent_system/backend/floodops/api/routes_timeline.py)

```python
"""Timeline frame endpoints for scrubber playback.

GET /api/v1/timeline/frames?start=-72h&end=+240h&step=1h
  → Returns array of forecast snapshots, one per hour:
    [{ time: "2026-06-07T00:00Z", flood_zones: GeoJSON, depth_grid: GeoJSON,
       pop_at_risk: 12400, phase: "02_IMMINENT", sensors: [...] }, ...]

GET /api/v1/timeline/phase-transitions
  → Returns timestamps and justifications for all phase changes:
    [{ time: "...", from: "01_ELEVATED", to: "02_IMMINENT", justification: "..." }, ...]

GET /api/v1/timeline/range
  → Returns { earliest: datetime, latest: datetime, now: datetime }
    for the scrubber to know its bounds
"""
```

---

### Component 8: Connectors — Cut to 4 Live + 6 Mocked

Effort reclaimed from connector integration is reinvested into UI.

---

#### 🟢 LIVE Connectors (real API calls)

| # | Connector | Why Live | Data Cadence |
|---|-----------|----------|-------------|
| 1 | **USGS** (`api.waterdata.usgs.gov`) | Genuinely real-time (15-min gauge readings), free API key | 🟢 15 min |
| 2 | **NWS/NOAA** (`api.weather.gov`) | Real-time alerts + radar, open API, GeoJSON native | 🟢 15 min |
| 3 | **ECMWF** (`cds.climate.copernicus.eu`) | The ensemble source — powers spaghetti/fan/disagreement | 🟡 6-hourly |
| 4 | **OSM** (`overpass-api.de`) | Road network for evacuation routing, building footprints | 🔵 Static (cached) |

#### ⚪ MOCK Connectors (realistic stubs, same `BaseConnector` interface)

| # | Connector | Mock Strategy | Swap-to-Live Later |
|---|-----------|--------------|---------------------|
| 5 | Sentinel Hub | Returns pre-baked SAR GeoTIFFs from sample data | Add OAuth creds + `sentinelhub` lib |
| 6 | Soil Moisture | Returns synthetic 0.25° grids matching real format | Add `cdsapi` retrieval |
| 7 | GLIMS | Static JSON of ~50 monitored lakes with properties | Add WFS calls via `OWSLib` |
| 8 | WorldPop | Synthetic population grids at 100m resolution | Add `worldpoppy` downloads |
| 9 | HydroSHEDS | Cached watershed boundaries + river network for demo region | Download shapefiles |
| 10 | Dartmouth | 5 historical flood events as CSV/GeoJSON | Add GEE access |

```python
# Every mock connector inherits from BaseConnector and returns data
# in the EXACT same format as the live version would.
# Swapping mock → live = change one config flag per connector.

class MockSentinelHubConnector(BaseConnector):
    """Returns pre-baked SAR data. Same interface as SentinelHubConnector."""
    
    async def get_sar_image(self, bbox, date_range):
        return self._load_sample("sar_sample.tiff")  # realistic sample
    
    async def get_flood_extent(self, bbox, date):
        return self._load_sample("flood_extent.geojson")
```

---

### Component 9: Data Cadence Honesty (`frontend/src/panels/data-cadence.js`)

No pretending 6-day satellites are "real-time."

```javascript
/**
 * Data cadence badges — shown in layer panel and on "why" cards.
 * 
 * Each data source displays its TRUE update frequency and last-seen time:
 * 
 *   🟢 USGS Gauges        15 min    (last: 3 min ago)
 *   🟢 NWS Alerts         15 min    (last: 8 min ago)
 *   🟡 ECMWF Ensemble     6 hours   (last: 2h ago)
 *   🟡 Sentinel-1 SAR     6-12 days (last: 4d ago)
 *   🟡 Soil Moisture      Daily     (last: 14h ago)
 *   ⚪ GLIMS Lakes         Static    (baseline inventory)
 *   ⚪ WorldPop            Annual    (2025 release)
 *   ⚪ HydroSHEDS          Static    (cached)
 *   🔵 OSM                On-demand (last query: 1h ago)
 * 
 * Color coding:
 *   🟢 = data is fresh relative to its expected cadence
 *   🟡 = data is within expected cadence but not the freshest
 *   🔴 = data is overdue / stale beyond its expected cadence
 *   ⚪ = static data (doesn't update frequently)
 *   🔵 = on-demand (queried when needed)
 * 
 * This honesty is critical. If the map shows a flood zone based on
 * 4-day-old SAR data + 3-minute-old gauge data, the user needs to know
 * the gauge is trustworthy but the SAR might be outdated.
 */
```

---

### Component 10: Premium Visual Design (`frontend/src/style.css`)

Not just "dark theme" — a designed system.

```css
/**
 * FloodOps Design System
 * 
 * PALETTE (HSL-based, not generic hex):
 * - Background:    hsl(220, 50%, 6%)    — near-black with blue undertone
 * - Surface:       hsl(220, 40%, 10%)   — elevated panels
 * - Glass:         hsla(220, 40%, 15%, 0.7) + backdrop-blur(20px) — glassmorphism
 * - Border:        hsla(220, 30%, 25%, 0.5) — subtle edge definition
 * 
 * RISK PALETTE (perceptually uniform):
 * - Minimal:  hsl(142, 70%, 45%)  — green
 * - Moderate: hsl(45, 95%, 55%)   — amber
 * - Severe:   hsl(25, 95%, 53%)   — orange
 * - Critical: hsl(0, 80%, 50%)    — red
 * - Emergency: hsl(0, 90%, 60%) + pulse animation — bright red + glow
 * 
 * TYPOGRAPHY:
 * - UI text: 'Inter', sans-serif (Google Fonts, variable weight)
 * - Data/numbers: 'JetBrains Mono', monospace (tabular figures)
 * - Phase labels: 'Inter', 600 weight, letterspacing 0.05em
 * 
 * MICRO-ANIMATIONS:
 * - Phase transition: 600ms spring easing on phase bar dot
 * - Layer toggle: 300ms opacity + 200ms blur transition
 * - "Why" card: 400ms slide-up + fade-in from click point
 * - Sensor pulse: infinite 2s radial pulse on anomaly markers
 * - Timeline play: CSS animation on play button → rotating border
 * - Scenario diff: 500ms morph between current and scenario outlines
 * 
 * GLASSMORPHISM PANELS:
 * - background: hsla(220, 40%, 15%, 0.7)
 * - backdrop-filter: blur(20px) saturate(1.2)
 * - border: 1px solid hsla(220, 30%, 30%, 0.3)
 * - border-radius: 16px
 * - box-shadow: 0 8px 32px hsla(0, 0%, 0%, 0.4)
 */
```

---

## Build Sequence (Reordered: UI First)

| Step | What | Files | Effort |
|------|------|-------|--------|
| **1** | Project setup: Vite frontend + FastAPI backend scaffolding | 6 | 5% |
| **2** | Pydantic models (all agents + ensemble + scenario + geo) | 13 | 8% |
| **3** | **3D Map engine**: Google Maps + deck.gl overlay + 7 layers + terrain tilt | 4 | **15%** |
| **4** | **Timeline scrubber**: scrubber UI + animator + keyframe interpolation | 3 | **12%** |
| **5** | **Ensemble visualization**: spaghetti + probability fan + disagreement badges | 4 | **10%** |
| **6** | **Spatial reasoning UI**: "why" cards + confidence renderer + hypotheses | 4 | **10%** |
| **7** | **What-if scenarios**: parameter panel + diff renderer + scenario API | 3+1 | **8%** |
| **8** | UI chrome: layer panel, phase bar, metrics, data cadence, design system | 5 | 7% |
| **9** | Event bus + agent skeletons + LangGraph orchestrator | 12 | 8% |
| **10** | 4 live connectors (USGS, NWS, ECMWF, OSM) + 6 mocks | 11 | 7% |
| **11** | LLM reasoning (data-grounded prompts, spatial "why" generation) | 3 | 5% |
| **12** | Auth (OAuth + Workspace) + WebSocket handler | 4 | 3% |
| **13** | Tests + integration verification | 5 | 2% |

**Total: ~78 files, frontend is ~40 of them. UI is 62% of effort.**

---

## Verification Plan

### Visual Verification (Primary)

1. Open app → map loads tilted 45° with dark theme and terrain
2. Mock flood scenario injects via `/api/v1/flood/simulate`
3. **3D depth columns** rise from flood zone cells (visible because map is tilted)
4. **Population hexbins** glow red where people overlap with flood depth
5. **Evacuation arcs** sweep from red zones to green shelter markers
6. **Timeline scrubber**: drag past → watch flood develop; drag future → watch forecast animate
7. **Ensemble spaghetti**: 10 lines diverge further into the future, showing growing uncertainty
8. **Probability fan**: click a map point → fan chart shows 5th-95th percentile spread
9. **Disagreement badge**: floating "40% catastrophic / 35% severe / 25% moderate" over contested zone
10. **"Why" card**: click a zone → card shows actual numbers, confidence bar, competing hypotheses, data cadence
11. **What-if**: slide rainfall to 200mm → click "Re-run" → flood zone expands with red dashed overlay
12. **Phase bar**: dots light up as system escalates through phases
13. **Data cadence**: each layer shows honest "last updated" with color-coded freshness

### Automated Tests

```bash
cd backend && python -m pytest tests/ -v

# Critical tests:
# - Full 7-phase state traversal with mock data
# - Ensemble member clustering (k-means for representative selection)
# - Timeline frame generation (correct GeoJSON per timestep)
# - Scenario re-run with modified parameters
# - "Why" card generation (LLM prompt contains actual numbers, not placeholders)
# - Connector interface compliance (mocks return same schema as live would)
```

---

## Credentials Required

| Service | What to Get | Where |
|---|---|---|
| Google Maps API Key | Maps JS API + Styled Maps | [Cloud Console](https://console.cloud.google.com) |
| Google OAuth Client | Client ID + Secret | Cloud Console → APIs & Services → Credentials |
| Google Gemini API Key | LLM reasoning | [AI Studio](https://aistudio.google.com) |
| USGS API Key | River gauge data | [USGS signup](https://api.waterdata.usgs.gov/signup/) |
| ECMWF CDS Token | Ensemble forecasts | [CDS Portal](https://cds.climate.copernicus.eu/) |
| Copernicus Client ID | (For future live Sentinel Hub) | [Copernicus CDSE](https://dataspace.copernicus.eu/) |
