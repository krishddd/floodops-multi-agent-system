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
import { getState, subscribe, setState } from './state.js';
import { connect, onMessage } from './websocket.js';

import { getMockData } from './mockData.js';
import { showToast } from './toast.js';

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
let _mapOverlay = null;

async function bootstrap() {
    console.log('🌊 Starting FloodOps v3...');

    // 1. Initialize Map
    const mapContainer = document.getElementById('map-container');
    const { map, overlay } = await initMap(mapContainer, window.FLOODOPS_CONFIG);
    _mapOverlay = overlay;
    setupInteractions(overlay);

    // 2. Initialize UI Panels
    initLayerPanel(renderFrame);
    initScenarioPanel();
    initChat();

    // 3. Connect WebSocket for live phase/event updates
    connect(window.FLOODOPS_CONFIG.wsUrl);
    
    onMessage('initial_state', (data) => {
        setState({ phase: data.phase, eventId: data.event_id });
        updatePhaseBar(data.phase);
    });
    
    onMessage('heartbeat', (data) => {
        if (data.phase !== getState().phase) {
            setState({ phase: data.phase });
            updatePhaseBar(data.phase);
        }
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

// Start
document.addEventListener('DOMContentLoaded', bootstrap);
