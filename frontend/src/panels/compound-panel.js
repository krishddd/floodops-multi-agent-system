/**
 * Compound Threat Radial — the signature multi-hazard gauge.
 *
 * Renders contributing hazards as spokes around a central hub showing the
 * unified threat score, plus the compounding factors and recommended action.
 * Pulses when a new compound threat arrives.
 */

const HAZARD_COLORS = {
    flood: '#3aa0ff',
    glof: '#7ee0ff',
    landslide: '#c98a3a',
    disease: '#b85cff',
    anomaly: '#ffd24a',
};

let _panel, _canvas, _meta;

export function initCompoundPanel() {
    _panel = document.getElementById('compound-panel');
    _canvas = document.getElementById('compound-radial');
    _meta = document.getElementById('compound-meta');
}

export function renderCompoundThreat(threat) {
    if (!_panel || !_canvas || !threat) return;
    _panel.style.display = 'block';
    _panel.classList.remove('pulse');
    // force reflow to restart the pulse animation
    void _panel.offsetWidth;
    _panel.classList.add('pulse');

    const hazards = threat.contributing_hazards || [];
    const score = threat.unified_threat_score ?? 0;
    _drawRadial(score, hazards);

    const factors = (threat.compounding_factors || [])
        .map(f => `<li>${escapeHtml(f)}</li>`).join('');
    _meta.innerHTML = `
        <div class="compound-score-row">
            <span class="compound-score" style="color:${scoreColor(score)}">${Math.round(score * 100)}%</span>
            <span class="compound-conf">conf ${Math.round((threat.confidence ?? 0) * 100)}%</span>
        </div>
        <div class="compound-hazards">
            ${hazards.map(h => `<span class="hz-chip" style="border-color:${HAZARD_COLORS[h.hazard_type] || '#888'}">
                ${h.hazard_type} ${Math.round((h.severity ?? 0) * 100)}%</span>`).join('')}
        </div>
        ${factors ? `<ul class="compound-factors">${factors}</ul>` : ''}
        <div class="compound-action">${escapeHtml(threat.recommended_action || '')}</div>
    `;
}

function _drawRadial(score, hazards) {
    const ctx = _canvas && _canvas.getContext && _canvas.getContext('2d');
    if (!ctx) return; // no 2d context (e.g. jsdom) — skip the canvas, keep meta
    const W = _canvas.width, H = _canvas.height;
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) / 2 - 30;
    ctx.clearRect(0, 0, W, H);

    // Concentric guide rings
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    for (let r = R; r > 0; r -= R / 4) {
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    }

    // Hazard spokes
    const n = Math.max(hazards.length, 1);
    hazards.forEach((h, i) => {
        const ang = (-Math.PI / 2) + (i / n) * Math.PI * 2;
        const sev = Math.max(0.05, h.severity ?? 0);
        const x = cx + Math.cos(ang) * R * sev;
        const y = cy + Math.sin(ang) * R * sev;
        const col = HAZARD_COLORS[h.hazard_type] || '#aaa';
        ctx.strokeStyle = col; ctx.lineWidth = 3;
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
        // label
        const lx = cx + Math.cos(ang) * (R + 14), ly = cy + Math.sin(ang) * (R + 14);
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(h.hazard_type, lx, ly);
    });

    // Central hub — unified score
    const hubR = R * 0.42;
    const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, hubR);
    grad.addColorStop(0, scoreColor(score));
    grad.addColorStop(1, 'rgba(10,15,26,0.9)');
    ctx.fillStyle = grad;
    ctx.beginPath(); ctx.arc(cx, cy, hubR, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = scoreColor(score); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(cx, cy, hubR, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.font = '600 22px Inter, sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(Math.round(score * 100) + '%', cx, cy);
}

function scoreColor(s) {
    if (s >= 0.8) return 'hsl(0,80%,55%)';
    if (s >= 0.5) return 'hsl(28,90%,55%)';
    if (s >= 0.3) return 'hsl(45,90%,55%)';
    return 'hsl(142,70%,45%)';
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
