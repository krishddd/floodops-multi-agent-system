import { describe, it, expect, beforeEach } from 'vitest';
import { initSkillPanel, renderSkillPanel } from '../panels/skill-panel.js';

describe('skill panel (v5)', () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <div id="skill-panel" style="display:none">
              <div id="skill-body"></div>
            </div>`;
        initSkillPanel();
    });

    it('renders the cold-start prior with an honest badge', () => {
        renderSkillPanel(
            { status: 'cold_start', samples: 3, min_samples: 20,
              prior: { 1: 0.55, 2: 0.45, 5: 0.35, 10: 0.28 } },
            { record_years: 30, thresholds_m3s: { 1: 11.3, 2: 100.6, 5: 147.0, 10: 182.1 } },
        );
        const badge = document.querySelector('.skill-badge');
        expect(badge.classList.contains('prior')).toBe(true);
        expect(badge.textContent).toContain('COLD-START PRIOR (3/20');
        const rows = document.querySelectorAll('.skill-table tbody tr');
        expect(rows.length).toBe(4);
        expect(rows[0].textContent).toContain('1-yr');
        expect(rows[0].textContent).toContain('0.55');
        expect(rows[0].textContent).toContain('11 m³/s');
        expect(document.querySelector('.skill-note').textContent)
            .toContain('30-yr GloFAS reanalysis');
        expect(document.getElementById('skill-panel').style.display).toBe('block');
    });

    it('renders measured skill with the measured badge', () => {
        renderSkillPanel(
            { status: 'measured', samples: 25, min_samples: 20,
              skill: { 2: { precision: 0.7, recall: 0.6, f1: 0.65 } } },
            null,
        );
        const badge = document.querySelector('.skill-badge');
        expect(badge.classList.contains('measured')).toBe(true);
        expect(badge.textContent).toContain('MEASURED (25 samples)');
        expect(document.querySelector('.skill-table tbody').textContent)
            .toContain('0.65');
    });

    it('surfaces a verifier error note', () => {
        renderSkillPanel(
            { status: 'cold_start', samples: 0, min_samples: 20, prior: {},
              last_run_ok: false, last_error: 'boom' },
            null,
        );
        expect(document.querySelector('.skill-warn').textContent).toContain('boom');
    });
});
