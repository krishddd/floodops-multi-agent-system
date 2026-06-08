/**
 * FloodOps state management — simple observable store.
 */
const _state = {
    phase: '00_MONITORING',
    eventId: '',
    layers: {
        floodZones: { visible: true, opacity: 0.8, data: null },
        floodDepth: { visible: true, opacity: 0.9, data: null },
        population: { visible: false, opacity: 0.7, data: null },
        evacuation: { visible: true, opacity: 0.85, data: null },
        spaghetti: { visible: false, opacity: 0.6, data: null },
        sensors: { visible: true, opacity: 0.95, data: null },
        glacialLakes: { visible: false, opacity: 0.8, data: null },
    },
    timeline: { currentFrame: 50, playing: false, speed: 4, frames: [] },
    ensemble: { members: [], fan: null, disagreement: null },
    metrics: { popAtRisk: 0, peakEta: '—', maxProbability: 0 },
    selectedFeature: null,
};

const _listeners = new Set();

export function getState() { return _state; }

export function setState(updates) {
    Object.assign(_state, updates);
    _listeners.forEach(fn => fn(_state));
}

export function updateLayer(name, updates) {
    if (_state.layers[name]) {
        Object.assign(_state.layers[name], updates);
        _listeners.forEach(fn => fn(_state));
    }
}

export function subscribe(fn) {
    _listeners.add(fn);
    return () => _listeners.delete(fn);
}
