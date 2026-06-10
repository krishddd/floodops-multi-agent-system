import { describe, it, expect, beforeEach, vi } from 'vitest';
import { connect, onMessage, onConnectionChange } from '../websocket.js';

// Minimal fake WebSocket to exercise message routing + connection state.
class FakeWS {
    constructor() {
        FakeWS.instances.push(this);
        this.readyState = 0;
    }
    close() {}
}
FakeWS.instances = [];
FakeWS.OPEN = 1;

describe('websocket routing + connection state', () => {
    beforeEach(() => {
        FakeWS.instances = [];
        vi.stubGlobal('WebSocket', FakeWS);
    });

    it('routes typed messages to the matching onMessage handler', () => {
        const received = [];
        onMessage('flood_forecasts', (data) => received.push(data));
        connect('ws://test/ws');
        const ws = FakeWS.instances[0];
        ws.onopen();
        ws.onmessage({ data: JSON.stringify({ type: 'flood_forecasts', data: { max_probability: 0.9 } }) });
        expect(received).toEqual([{ max_probability: 0.9 }]);
    });

    it('reports live on open and reconnecting on close', () => {
        const states = [];
        onConnectionChange((s) => states.push(s));
        connect('ws://test/ws');
        const ws = FakeWS.instances[0];
        ws.onopen();
        ws.onclose();
        expect(states).toContain('live');
        expect(states.some((s) => s === 'reconnecting' || s === 'offline')).toBe(true);
    });
});
