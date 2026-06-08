/** Ensemble spaghetti — fetch and prepare member data for PathLayer rendering. */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export async function fetchSpaghettiData(time = 'T+24h') {
    try {
        const resp = await fetch(`${API}/ensemble/members?time=${time}`);
        const data = await resp.json();
        return data.members || [];
    } catch (e) {
        return [];
    }
}

export async function fetchRepresentatives(n = 10) {
    try {
        const resp = await fetch(`${API}/ensemble/representatives?n=${n}`);
        const data = await resp.json();
        return data.representative_ids || [];
    } catch (e) {
        return [];
    }
}
