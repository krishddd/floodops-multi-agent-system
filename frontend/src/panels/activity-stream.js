/**
 * Agent Activity Stream — live, color-per-agent feed of agent actions.
 * Fed by WebSocket channel events and the /flood/audit endpoint.
 */

const AGENT_COLORS = {
    sentinel_agent: '#ffd24a',
    glof_agent: '#7ee0ff',
    flood_predict_agent: '#3aa0ff',
    urban_risk_agent: '#5ad19a',
    alert_agent: '#ff6b6b',
    resource_agent: '#c98a3a',
    disease_risk_agent: '#b85cff',
    compound_event_agent: '#ff4d4d',
};

// Map a WS channel to a human label + which agent produced it.
const CHANNEL_META = {
    anomaly_alerts: { agent: 'sentinel_agent', verb: 'anomaly detected' },
    flood_forecasts: { agent: 'flood_predict_agent', verb: 'forecast emitted' },
    urban_risk: { agent: 'urban_risk_agent', verb: 'urban risk mapped' },
    alert_dispatches: { agent: 'alert_agent', verb: 'alert dispatched' },
    glof_emergencies: { agent: 'glof_agent', verb: 'GLOF emergency' },
    disease_risk: { agent: 'disease_risk_agent', verb: 'disease risk' },
    resource_orders: { agent: 'resource_agent', verb: 'resources ordered' },
    compound_threats: { agent: 'compound_event_agent', verb: 'compound threat' },
    agent_errors: { agent: 'system', verb: 'error' },
};

let _stream;

export function initActivityStream() {
    _stream = document.getElementById('activity-stream');
}

/** Record an event from a WS channel into the stream. */
export function recordChannelEvent(channel, data) {
    const meta = CHANNEL_META[channel];
    if (!meta) return;
    const detail = summarize(channel, data);
    addEntry({ agent: meta.agent, verb: meta.verb, detail,
               error: channel === 'agent_errors' });
}

function summarize(channel, d) {
    if (!d) return '';
    if (channel === 'flood_forecasts') return `${pct(d.max_probability)} max probability`;
    if (channel === 'compound_threats') return `${pct(d.unified_threat_score)} unified threat`;
    if (channel === 'alert_dispatches') return `${d.severity || ''}`.trim();
    if (channel === 'urban_risk') return `${(d.zones || []).length} zones, ${fmt(d.total_population_at_risk)} at risk`;
    if (channel === 'disease_risk') return `${(d.hotspots || []).length} hotspots`;
    if (channel === 'anomaly_alerts') return `${d.level || ''} ${d.deviation_sigma ? d.deviation_sigma + 'σ' : ''}`.trim();
    if (channel === 'agent_errors') return `${d.channel || ''}: ${d.error || ''}`;
    return '';
}

function addEntry({ agent, verb, detail, error }) {
    if (!_stream) return;
    const color = error ? '#ff5c5c' : (AGENT_COLORS[agent] || '#9fb3c8');
    const row = document.createElement('div');
    row.className = 'activity-row' + (error ? ' activity-error' : '');
    const t = new Date().toLocaleTimeString([], { hour12: false });
    row.innerHTML = `
        <span class="activity-time">${t}</span>
        <span class="activity-agent" style="color:${color}">${shortAgent(agent)}</span>
        <span class="activity-detail">${verb}${detail ? ' — ' + escapeHtml(detail) : ''}</span>`;
    _stream.prepend(row);
    while (_stream.children.length > 40) _stream.lastChild.remove();
    // entry-in animation
    requestAnimationFrame(() => row.classList.add('shown'));
}

function shortAgent(a) {
    return (a || '').replace(/_agent$/, '').replace(/_/g, ' ');
}
function pct(v) { return v == null ? '—' : Math.round(v * 100) + '%'; }
function fmt(n) { return n == null ? '0' : Number(n).toLocaleString(); }
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
