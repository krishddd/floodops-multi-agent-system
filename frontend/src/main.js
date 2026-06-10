/**
 * FloodOps v3 — Main application bootstrap.
 * Wires the map, websocket, state, and UI panels together.
 */
import { initMap, updateLayers } from './map/init.js';
import { buildLayers } from './map/layers.js';
import { setupInteractions } from './map/interactions.js';
import { initTimeline, getCurrentFrame } from './timeline/scrubber.js';
import { initScenarioPanel } from './scenarios/scenario-panel.js';
import { initLayerPanel, renderDataCadence } from './panels/layer-panel.js';
import { updatePhaseBar, updateMetrics } from './panels/phase-bar.js';
import { initChat } from './panels/chat.js';
import { renderProbabilityFan } from './ensemble/probability-fan.js';
import { renderDisagreementBadge, fetchDisagreement } from './ensemble/disagreement.js';
import { fetchSpaghettiData, fetchRepresentatives } from './ensemble/spaghetti.js';
import { getState, subscribe, setState, pushCompoundThreat } from './state.js';
import { connect, onMessage, onConnectionChange } from './websocket.js';
import { initCompoundPanel, renderCompoundThreat } from './panels/compound-panel.js';
import { initActivityStream, recordChannelEvent } from './panels/activity-stream.js';
import { initSitrep, refreshSitrep } from './panels/sitrep.js';
import { initAreaSearch } from './panels/area-search.js';

import { getMockData } from './mockData.js';
import { showToast } from './toast.js';

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
let _mapOverlay = null;

async function bootstrap() {
    console.log('🌊 Starting FloodOps v3...');

    // 1. Initialize Map (resilient — the command deck still works with no
    //    Google Maps key; the basemap simply won't render).
    const mapContainer = document.getElementById('map-container');
    // Google calls this global on auth failure (bad key, referrer not allowed,
    // API not enabled, billing off). Without it the map just stays blank/dark
    // with no explanation — surface the real reason instead.
    window.gm_authFailure = () => {
        console.error(
            'Google Maps auth FAILED. Common causes:\n' +
            '  • API key restricted to referrers that exclude http://localhost:5173/* \n' +
            '  • Maps JavaScript API not enabled on the key\'s project\n' +
            '  • Billing not enabled on the Cloud project\n' +
            'Fix in Cloud Console → APIs & Services → Credentials → your key.'
        );
        mapContainer.classList.add('map-disabled');
        showToast('Google Maps auth failed — check key restrictions/billing (see console)', 'error');
    };

    const mapsKey = window.FLOODOPS_CONFIG.mapsApiKey;
    try {
        if (!mapsKey || mapsKey.startsWith('%')) {
            // Empty, or an unsubstituted Vite placeholder (dev server not restarted).
            throw new Error(
                mapsKey.startsWith('%')
                    ? 'Maps key is an unsubstituted %VITE_…% placeholder — restart `npm run dev`'
                    : 'no Maps key configured'
            );
        }
        const { overlay } = await initMap(mapContainer, window.FLOODOPS_CONFIG);
        _mapOverlay = overlay;
        setupInteractions(overlay);
        console.log('🗺️ Map initialized');
    } catch (e) {
        console.warn('Map init skipped — panels still live. Reason:', e.message);
        mapContainer.classList.add('map-disabled');
        showToast(`Map disabled: ${e.message}`, 'warning');
    }

    // 2. Initialize UI Panels
    initLayerPanel(renderFrame);
    initScenarioPanel();
    initChat();
    initCompoundPanel();
    initActivityStream();
    initSitrep();
    initAreaSearch();

    // 3. Connect WebSocket for live phase/event updates + live agent stream
    connect(window.FLOODOPS_CONFIG.wsUrl);
    onConnectionChange(updateConnHud);
    wireLiveChannels();

    onMessage('initial_state', (data) => {
        // Full snapshot — also resyncs phase, sitrep, and compound threats.
        setState({ phase: data.phase, eventId: data.event_id });
        updatePhaseBar(data.phase);
        if (Array.isArray(data.compound_threats) && data.compound_threats.length) {
            const latest = data.compound_threats[data.compound_threats.length - 1];
            pushCompoundThreat(latest);
            renderCompoundThreat(latest);
        }
        refreshSitrep();
    });

    onMessage('heartbeat', (data) => {
        if (data.phase && data.phase !== getState().phase) {
            setState({ phase: data.phase });
            updatePhaseBar(data.phase);
        }
    });

    onMessage('phase_transition', (data) => {
        setState({ phase: data.phase });
        updatePhaseBar(data.phase);
        triggerPhaseSweep();
        refreshSitrep();
        showToast(`Phase → ${(data.phase || '').replace(/^\d+_/, '')}`, 'warning');
    });

    // 4. Initialize Timeline & fetch initial data
    await initTimeline((frame) => {
        updateMetrics(frame);
        renderFrame();
    });

    // 5. Initial Data Load (fetch static GeoJSON layers)
    await loadInitialData();

    // Hide Splash Screen
    const splash = document.getElementById('splash-screen');
    if (splash) {
        splash.classList.add('hide');
        setTimeout(() => splash.remove(), 600);
    }
}

async function loadInitialData() {
    try {
        const [floodZones, floodDepth, population, evacuation, sensors, lakes] = await Promise.all([
            fetch(`${API}/map/flood-zones`).then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(`${API}/map/flood-depth`).then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(`${API}/map/population-risk`).then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(`${API}/map/evacuation-routes`).then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(`${API}/map/sensors`).then(r => r.ok ? r.json() : null).catch(() => null),
            fetch(`${API}/map/glacial-lakes`).then(r => r.ok ? r.json() : null).catch(() => null),
        ]);

        if (!floodDepth && !population) throw new Error("Backend unavailable");

        const spaghetti = await fetchSpaghettiData('T+24h');

        setState({
            layerData: {
                floodZones: floodZones || { type: "FeatureCollection", features: [] },
                floodDepth: floodDepth || { type: "FeatureCollection", features: [] },
                population: population?.points || [],
                evacuation: evacuation?.routes || [],
                spaghetti,
                sensors: sensors || { type: "FeatureCollection", features: [] },
                glacialLakes: lakes || { type: "FeatureCollection", features: [] },
            }
        });

        showToast('Connected to Live Stream', 'success');
        
    } catch (e) {
        console.warn('Failed to load live map layers. Using Mock Data fallback.', e);
        showToast('Backend offline — using mock data', 'warning');
        const mockLayerData = await getMockData(window.FLOODOPS_CONFIG.center.lat, window.FLOODOPS_CONFIG.center.lng);
        setState({ layerData: mockLayerData });
    }

    // Initialize ensemble fan
    const fanCanvas = document.getElementById('probability-fan-canvas');
    if (fanCanvas) {
        document.getElementById('ensemble-panel').style.display = 'block';
        await renderProbabilityFan(fanCanvas, window.FLOODOPS_CONFIG.center.lat, window.FLOODOPS_CONFIG.center.lng);
        
        const badgeContainer = document.getElementById('disagreement-badges');
        const disagreement = await fetchDisagreement('zone_1');
        if (disagreement && badgeContainer) renderDisagreementBadge(badgeContainer, disagreement);
    }

    renderFrame();
}

function renderFrame() {
    const state = getState();
    if (!state.layerData || !_mapOverlay) return;

    // Apply any time-specific filters to layerData based on current frame
    // (In a full implementation, you'd filter features by time here)

    const layers = buildLayers(state.layerData, state.layers);
    updateLayers(layers);
}

// ── Live agent stream wiring ─────────────────────────────────────────
const LIVE_CHANNELS = [
    'anomaly_alerts', 'flood_forecasts', 'urban_risk', 'alert_dispatches',
    'glof_emergencies', 'disease_risk', 'resource_orders', 'compound_threats',
    'agent_errors',
];

function wireLiveChannels() {
    LIVE_CHANNELS.forEach((channel) => {
        onMessage(channel, (data) => {
            recordChannelEvent(channel, data);
            if (channel === 'flood_forecasts' && data && data.max_probability != null) {
                setState({ metrics: { ...getState().metrics,
                    maxProbability: data.max_probability } });
                updateMetrics({ max_probability: data.max_probability });
            }
            if (channel === 'compound_threats' && data) {
                pushCompoundThreat(data);
                renderCompoundThreat(data);
            }
            pulseLive();
        });
    });
}

function updateConnHud(state) {
    const hud = document.getElementById('conn-hud');
    const label = document.getElementById('conn-label');
    if (!hud || !label) return;
    hud.classList.remove('live', 'reconnecting', 'offline', 'connecting');
    hud.classList.add(state);
    label.textContent = ({
        live: 'Live', reconnecting: 'Reconnecting…', offline: 'Offline',
        connecting: 'Connecting…',
    })[state] || state;
}

let _pulseTimer = null;
function pulseLive() {
    const pip = document.getElementById('activity-live');
    if (!pip) return;
    pip.classList.add('on');
    clearTimeout(_pulseTimer);
    _pulseTimer = setTimeout(() => pip.classList.remove('on'), 400);
}

function triggerPhaseSweep() {
    const el = document.body;
    el.classList.remove('phase-sweep');
    void el.offsetWidth;
    el.classList.add('phase-sweep');
    setTimeout(() => el.classList.remove('phase-sweep'), 1200);
}

// Start
document.addEventListener('DOMContentLoaded', bootstrap);
