import { describe, it, expect } from 'vitest';
import { getState, setState, pushActivity, pushCompoundThreat, subscribe } from '../state.js';

describe('state store', () => {
    it('setState merges and notifies subscribers', () => {
        let calls = 0;
        const unsub = subscribe(() => { calls += 1; });
        setState({ phase: '02_IMMINENT' });
        expect(getState().phase).toBe('02_IMMINENT');
        expect(calls).toBeGreaterThan(0);
        unsub();
    });

    it('pushActivity is bounded and newest-first', () => {
        for (let i = 0; i < 80; i++) pushActivity({ verb: 'x', n: i });
        const log = getState().auditLog;
        expect(log.length).toBeLessThanOrEqual(60);
        expect(log[0].n).toBe(79); // newest first
    });

    it('pushCompoundThreat prepends and caps at 20', () => {
        for (let i = 0; i < 25; i++) pushCompoundThreat({ unified_threat_score: i / 25 });
        const t = getState().compoundThreats;
        expect(t.length).toBe(20);
    });
});
