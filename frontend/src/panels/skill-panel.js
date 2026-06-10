/**
 * Forecast Skill & Benchmark panel (v5).
 *
 * Surfaces the two science endpoints shipped in v4:
 *   - /verification/skill  — measured precision/recall/F1 per return period
 *     (paper's ±2-day rule), or the labelled cold-start prior;
 *   - /basin/thresholds    — per-basin return-period discharge thresholds
 *     fitted from the GloFAS reanalysis.
 *
 * Honest by design: the badge says MEASURED vs PRIOR so an operator can
 * never mistake reference values for verified skill.
 */

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
let _panel, _body, _timer;

export function initSkillPanel() {
    _panel = document.getElementById('skill-panel');
    _body = document.getElementById('skill-body');
    refreshSkillPanel();
    _timer = setInterval(refreshSkillPanel, 5 * 60 * 1000);
}

export async function refreshSkillPanel() {
    if (!_panel || !_body) return;
    try {
        const headers = {};
        const apiKey = (window.FLOODOPS_CONFIG || {}).API_KEY;
        if (apiKey) headers['X-API-Key'] = apiKey;
        const [skillResp, thrResp] = await Promise.all([
            fetch(`${API}/verification/skill`, { headers }),
            fetch(`${API}/basin/thresholds`, { headers }),
        ]);
        if (!skillResp.ok) return;
        const skill = await skillResp.json();
        const thresholds = thrResp.ok ? await thrResp.json() : null;
        renderSkillPanel(skill, thresholds);
    } catch (_e) { /* backend offline — keep prior render */ }
}

/** Render from data (exported separately so tests need no fetch). */
export function renderSkillPanel(skill, thresholds) {
    if (!_panel || !_body) return;
    const measured = skill.status === 'measured';
    const f1ByRp = measured
        ? Object.fromEntries(Object.entries(skill.skill).map(([rp, s]) => [rp, s.f1]))
        : (skill.prior || {});
    const thrByRp = (thresholds && thresholds.thresholds_m3s) || {};

    const rps = [...new Set([...Object.keys(f1ByRp), ...Object.keys(thrByRp)])]
        .map(Number).sort((a, b) => a - b);

    const rows = rps.map((rp) => {
        const f1 = f1ByRp[rp] != null ? Number(f1ByRp[rp]).toFixed(2) : '—';
        const thr = thrByRp[rp] != null ? `${Math.round(thrByRp[rp])} m³/s` : '—';
        return `<tr><td>${rp}-yr</td><td>${f1}</td><td>${thr}</td></tr>`;
    }).join('');

    const badgeClass = measured ? 'skill-badge measured' : 'skill-badge prior';
    const badgeText = measured
        ? `MEASURED (${skill.samples} samples)`
        : `COLD-START PRIOR (${skill.samples}/${skill.min_samples} samples)`;
    const record = thresholds && thresholds.record_years
        ? `<div class="skill-note">Thresholds: ${thresholds.record_years}-yr GloFAS reanalysis fit</div>`
        : '';
    const health = skill.last_run_ok === false
        ? `<div class="skill-note skill-warn">verifier error: ${skill.last_error || '?'}</div>`
        : '';

    _body.innerHTML = `
        <span class="${badgeClass}">${badgeText}</span>
        <table class="skill-table">
            <thead><tr><th>Event</th><th>F1</th><th>Threshold</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
        ${record}${health}`;
    _panel.style.display = 'block';
}
