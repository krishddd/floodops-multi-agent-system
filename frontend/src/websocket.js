/**
 * WebSocket client with auto-reconnect and message type routing.
 */
let _ws = null;
let _reconnectTimer = null;
let _reconnectAttempts = 0;
const _handlers = {};

export function onMessage(type, handler) {
    if (!_handlers[type]) _handlers[type] = [];
    _handlers[type].push(handler);
}

export function connect(url) {
    if (_ws && _ws.readyState === WebSocket.OPEN) return;

    _ws = new WebSocket(url);

    _ws.onopen = () => {
        console.log('🔌 WebSocket connected');
        _reconnectAttempts = 0;
        if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    };

    _ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            const handlers = _handlers[msg.type] || [];
            handlers.forEach(fn => fn(msg.data || msg));
            // Also fire 'all' handlers
            (_handlers['*'] || []).forEach(fn => fn(msg));
        } catch (e) { console.warn('WS parse error:', e); }
    };

    _ws.onclose = () => {
        let delay = Math.min(1000 * Math.pow(1.5, _reconnectAttempts), 30000); // Max 30s
        console.log(`🔌 WebSocket disconnected — reconnecting in ${Math.round(delay/1000)}s`);
        _reconnectAttempts++;
        _reconnectTimer = setTimeout(() => connect(url), delay);
    };

    _ws.onerror = (err) => console.error('WS error:', err);
}

export function send(data) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
        _ws.send(JSON.stringify(data));
    }
}
