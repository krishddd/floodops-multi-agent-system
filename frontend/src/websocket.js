/**
 * WebSocket client with auto-reconnect and message type routing.
 */
let _ws = null;
let _reconnectTimer = null;
let _reconnectAttempts = 0;
let _hasConnectedOnce = false;
const _handlers = {};
const _connListeners = new Set();

export function onMessage(type, handler) {
    if (!_handlers[type]) _handlers[type] = [];
    _handlers[type].push(handler);
}

/** Subscribe to connection-state changes: live | reconnecting | offline. */
export function onConnectionChange(fn) {
    _connListeners.add(fn);
    return () => _connListeners.delete(fn);
}

function _setConn(state) {
    _connListeners.forEach(fn => fn(state));
}

export function connect(url) {
    if (_ws && _ws.readyState === WebSocket.OPEN) return;

    // v4 auth: browsers cannot set custom WS headers, so the API key (when
    // configured) rides as a query param on the upgrade request.
    const apiKey = (window.FLOODOPS_CONFIG || {}).API_KEY;
    if (apiKey) {
        url += (url.includes('?') ? '&' : '?') + 'api_key=' + encodeURIComponent(apiKey);
    }

    _ws = new WebSocket(url);

    _ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        const wasReconnect = _hasConnectedOnce;
        _hasConnectedOnce = true;
        _reconnectAttempts = 0;
        if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
        _setConn('live');
        // On reconnect the backend re-sends a full `initial_state` snapshot, so
        // existing `initial_state` handlers perform the resync automatically.
        if (wasReconnect) console.log('🔄 reconnected — awaiting snapshot resync');
    };

    _ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            const handlers = _handlers[msg.type] || [];
            handlers.forEach(fn => fn(msg.data ?? msg, msg));
            (_handlers['*'] || []).forEach(fn => fn(msg));
        } catch (e) { console.warn('WS parse error:', e); }
    };

    _ws.onclose = () => {
        let delay = Math.min(1000 * Math.pow(1.5, _reconnectAttempts), 30000);
        console.log(`🔌 WebSocket disconnected — reconnecting in ${Math.round(delay/1000)}s`);
        _reconnectAttempts++;
        _setConn(_reconnectAttempts > 4 ? 'offline' : 'reconnecting');
        _reconnectTimer = setTimeout(() => connect(url), delay);
    };

    _ws.onerror = (err) => console.error('WS error:', err);
}

export function send(data) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
        _ws.send(JSON.stringify(data));
    }
}
