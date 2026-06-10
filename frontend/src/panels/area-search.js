/**
 * Area search — type a city/place → recenter the map → run the pipeline there.
 *
 * Geocoding uses Open-Meteo's free, keyless geocoding API (no Google Places /
 * billing needed), keeping with the app's keyless-by-default connectors.
 */
import { getMap } from '../map/init.js';
import { showToast } from '../toast.js';

const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';
const GEOCODE = 'https://geocoding-api.open-meteo.com/v1/search';

async function geocode(query) {
    const url = `${GEOCODE}?name=${encodeURIComponent(query)}&count=1&language=en&format=json`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`geocoder ${r.status}`);
    const data = await r.json();
    const hit = data?.results?.[0];
    if (!hit) throw new Error('no match');
    const label = [hit.name, hit.admin1, hit.country_code].filter(Boolean).join(', ');
    return { lat: hit.latitude, lng: hit.longitude, name: label };
}

async function runArea(place) {
    // 1. Recenter the basemap if it loaded (it may be disabled with no key).
    const map = getMap();
    if (map) {
        map.panTo({ lat: place.lat, lng: place.lng });
        map.setZoom(11);
    }
    if (window.FLOODOPS_CONFIG) {
        window.FLOODOPS_CONFIG.center = { lat: place.lat, lng: place.lng };
    }

    // 2. Trigger the pipeline for this area (real weather/OSM is fetched for it).
    const res = await fetch(`${API}/flood/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat: place.lat, lng: place.lng, name: place.name }),
    });
    if (!res.ok) throw new Error(`simulate ${res.status}`);
    return res.json();
}

export function initAreaSearch() {
    const input = document.getElementById('area-input');
    const btn = document.getElementById('area-go');
    if (!input || !btn) return;

    async function submit() {
        const query = input.value.trim();
        if (!query) return;
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = 'Locating…';
        try {
            const place = await geocode(query);
            showToast(`Targeting ${place.name} — running pipeline…`, 'success');
            await runArea(place);
            input.value = place.name;
        } catch (e) {
            const msg = e.message === 'no match'
                ? `No place found for "${query}"`
                : `Area search failed: ${e.message}`;
            showToast(msg, 'warning');
            console.warn('area-search:', e);
        } finally {
            btn.disabled = false;
            btn.textContent = original;
        }
    }

    btn.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
}
