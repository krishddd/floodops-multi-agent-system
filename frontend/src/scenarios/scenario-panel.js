/** What-if scenario panel controller. */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export function initScenarioPanel() {
    const rainfall = document.getElementById('rainfall-slider');
    const soil = document.getElementById('soil-slider');
    const dam = document.getElementById('dam-slider');
    const run = document.getElementById('scenario-run');

    if (rainfall) rainfall.addEventListener('input', () => { document.getElementById('rainfall-val').textContent = rainfall.value; });
    if (soil) soil.addEventListener('input', () => { document.getElementById('soil-val').textContent = soil.value; });
    if (dam) dam.addEventListener('input', () => { document.getElementById('dam-val').textContent = dam.value > 0 ? dam.value : '—'; });

    if (run) run.addEventListener('click', runScenario);
}

async function runScenario() {
    const rainfall = parseInt(document.getElementById('rainfall-slider')?.value || 120);
    const soil = parseInt(document.getElementById('soil-slider')?.value || 85);
    const dam = parseInt(document.getElementById('dam-slider')?.value || 0);

    const params = { rainfall_mm_24h: rainfall, soil_saturation_pct: soil };
    if (dam > 0) { params.dam_break_time_h = dam; params.dam_break_lake_id = 'GL003'; }

    document.getElementById('scenario-run').textContent = '⏳ Computing...';
    try {
        const resp = await fetch(`${API}/scenario/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params) });
        const result = await resp.json();
        renderDiff(result.diff);
    } catch (e) {
        document.getElementById('scenario-diff').innerHTML = '<div style="color:var(--text-dim)">Backend unavailable</div>';
    }
    document.getElementById('scenario-run').textContent = '▶ Re-run Forecast';
}

function renderDiff(diff) {
    if (!diff) return;
    const container = document.getElementById('scenario-diff');
    const items = [
        { label: 'Population', val: diff.delta_population_at_risk, fmt: v => `${v > 0 ? '+' : ''}${v.toLocaleString()}` },
        { label: 'Peak Depth', val: diff.delta_peak_depth_m, fmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)}m` },
        { label: 'Peak Time', val: diff.delta_peak_time_hours, fmt: v => `${v > 0 ? '+' : ''}${v}h` },
        { label: 'Extent', val: diff.delta_flood_extent_km2, fmt: v => `${v > 0 ? '+' : ''}${v.toFixed(1)} km²` },
    ];
    container.innerHTML = items.map(i =>
        `<div style="margin:4px 0"><span style="color:var(--text-dim)">${i.label}:</span> <span class="${i.val > 0 ? 'diff-positive' : 'diff-negative'}">${i.fmt(i.val)}</span></div>`
    ).join('') + (diff.summary ? `<div style="margin-top:8px;color:var(--text-secondary);font-size:11px;font-family:var(--font-ui)">${diff.summary}</div>` : '');
}
