/**
 * Sitrep ticker — LLM situation report in a top HUD ticker.
 * Refreshed on phase changes and periodically.
 */

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
let _ticker, _text, _timer;

export function initSitrep() {
    _ticker = document.getElementById('sitrep-ticker');
    _text = document.getElementById('sitrep-text');
    refreshSitrep();
    // Periodic refresh (sitrep is cheap when the LLM is mocked).
    _timer = setInterval(refreshSitrep, 60000);
}

export async function refreshSitrep() {
    if (!_ticker || !_text) return;
    try {
        const resp = await fetch(`${API}/flood/sitrep`);
        if (!resp.ok) return;
        const data = await resp.json();
        const text = (data.sitrep || '').trim();
        if (text) {
            _text.textContent = text;
            _ticker.style.display = 'flex';
        }
    } catch (_e) { /* backend offline — leave prior text */ }
}
