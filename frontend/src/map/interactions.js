/**
 * Map interaction handlers — click opens "why" card, hover shows tooltip.
 */
import { getState } from '../state.js';

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export function setupInteractions(overlay) {
    // deck.gl picks via onHover/onClick in layer props
    // We handle the response here
}

export async function handleFeatureClick(info, event) {
    if (!info.object) return;

    const props = info.object.properties || info.object;
    const zoneId = props.zone_id || info.object.id || props.id || 'zone_1';
    const card = document.getElementById('why-card');

    try {
        const resp = await fetch(`${API}/flood/reasoning?zone_id=${zoneId}`);
        const data = await resp.json();
        renderWhyCard(card, data, info.x, info.y);
    } catch (e) {
        renderWhyCard(card, {
            feature_name: props.zone_name || props.name || zoneId,
            explanation: 'Reasoning service unavailable — start the backend.',
            confidence: props.confidence || props.risk_score || 0.5,
            metrics: props,
        }, info.x, info.y);
    }
}

function renderWhyCard(card, data, x, y) {
    const confidence = data.confidence || 0.5;
    const riskPct = Math.round(confidence * 100);
    const riskColor = confidence > 0.8 ? 'var(--risk-critical)' : confidence > 0.6 ? 'var(--risk-severe)' : confidence > 0.3 ? 'var(--risk-moderate)' : 'var(--risk-minimal)';

    card.innerHTML = `
        <button class="why-card-close" onclick="this.parentElement.style.display='none'">✕</button>
        <div class="why-card-title">${data.feature_name || 'Unknown Feature'}</div>
        <div class="why-card-risk">
            <span>Risk</span>
            <div class="risk-bar"><div class="risk-bar-fill" style="width:${riskPct}%;background:${riskColor}"></div></div>
            <span style="font-family:var(--font-mono);font-size:13px">${riskPct}%</span>
        </div>
        <div style="font-size:13px;line-height:1.6;color:var(--text-secondary)">${data.explanation || ''}</div>
        ${data.confidence_explanation ? `<div class="confidence-bar"><div class="confidence-bar-fill" style="width:${riskPct}%"></div></div><small style="color:var(--text-dim)">${data.confidence_explanation}</small>` : ''}
        ${data.majority_view ? `<div class="why-card-section"><h4>Majority View (${Math.round((data.majority_pct || 0.76) * 100)}%)</h4><p style="font-size:12px">${data.majority_view}</p></div>` : ''}
        ${data.minority_view ? `<div class="competing-view"><strong>Competing View (${Math.round((data.minority_pct || 0.24) * 100)}%)</strong><br>${data.minority_view}</div>` : ''}
        ${data.data_sources ? `<div class="source-badges">${data.data_sources.map(s => `<span class="source-badge">${s.freshness_emoji} ${s.source_name} ${s.last_reading_ago}</span>`).join('')}</div>` : ''}
    `;

    // Position near click, but keep on screen
    const maxX = window.innerWidth - 420;
    const maxY = window.innerHeight - 400;
    card.style.left = Math.min(x + 20, maxX) + 'px';
    card.style.top = Math.min(y - 50, maxY) + 'px';
    card.style.display = 'block';
}
