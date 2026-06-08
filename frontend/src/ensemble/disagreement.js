/** Disagreement badges — floating outcome breakdowns. */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export async function fetchDisagreement(zoneId) {
    try {
        const resp = await fetch(`${API}/ensemble/disagreement?zone_id=${zoneId}`);
        return await resp.json();
    } catch (e) { return null; }
}

export function renderDisagreementBadge(container, data) {
    if (!data || !container) return;
    const items = [
        { pct: data.catastrophic_pct, label: 'catastrophic', emoji: '🔴' },
        { pct: data.severe_pct, label: 'severe', emoji: '🟠' },
        { pct: data.moderate_pct, label: 'moderate', emoji: '🟡' },
        { pct: data.minimal_pct, label: 'minimal', emoji: '🟢' },
    ].filter(i => i.pct > 0.05);

    container.innerHTML = `<div class="panel-title">Ensemble Disagreement</div>` +
        items.map(i => `<div style="font-size:12px;margin:4px 0">${i.emoji} ${Math.round(i.pct * 100)}% of members: <strong>${i.label}</strong></div>`).join('');
}
