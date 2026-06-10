import { describe, it, expect, beforeEach } from 'vitest';
import { initCompoundPanel, renderCompoundThreat } from '../panels/compound-panel.js';
import { initActivityStream, recordChannelEvent } from '../panels/activity-stream.js';

// Lifecycle smoke tests for the highest-risk new components — assert they
// render with mock data without throwing (no pixel assertions).

describe('panel lifecycle', () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <div id="compound-panel" style="display:none">
              <canvas id="compound-radial" width="240" height="240"></canvas>
              <div id="compound-meta"></div>
            </div>
            <div id="activity-stream"></div>`;
    });

    it('compound radial renders a threat without throwing', () => {
        initCompoundPanel();
        expect(() => renderCompoundThreat({
            unified_threat_score: 1.0,
            confidence: 0.79,
            contributing_hazards: [
                { hazard_type: 'flood', severity: 0.9 },
                { hazard_type: 'landslide', severity: 0.76 },
            ],
            compounding_factors: ['Flood saturation destabilizes slopes'],
            recommended_action: 'UNIFIED EMERGENCY COMMAND',
        })).not.toThrow();
        expect(document.getElementById('compound-panel').style.display).toBe('block');
        expect(document.querySelector('.compound-score').textContent).toBe('100%');
        expect(document.querySelectorAll('.hz-chip').length).toBe(2);
    });

    it('activity stream records a channel event', () => {
        initActivityStream();
        recordChannelEvent('flood_forecasts', { max_probability: 0.9 });
        const rows = document.querySelectorAll('#activity-stream .activity-row');
        expect(rows.length).toBe(1);
        expect(rows[0].textContent).toContain('forecast emitted');
    });

    it('activity stream is bounded', () => {
        initActivityStream();
        for (let i = 0; i < 50; i++) recordChannelEvent('flood_forecasts', { max_probability: 0.5 });
        expect(document.querySelectorAll('#activity-stream .activity-row').length).toBeLessThanOrEqual(40);
    });
});
