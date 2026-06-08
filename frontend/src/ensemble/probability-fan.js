/**
 * Probability fan chart — Canvas-based 5th–95th percentile visualization.
 */
const API = window.FLOODOPS_CONFIG?.apiUrl || '/api/v1';

export async function renderProbabilityFan(canvas, lat, lng) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;

    let data;
    try {
        const resp = await fetch(`${API}/ensemble/fan?lat=${lat}&lng=${lng}`);
        data = await resp.json();
    } catch (e) {
        ctx.fillStyle = '#1a2332';
        ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = '#556';
        ctx.font = '12px Inter';
        ctx.fillText('Fan chart unavailable — start backend', 20, h / 2);
        return;
    }

    const steps = data.time_steps || [];
    const pctls = data.percentiles || {};
    const maxVal = 6;

    // Clear
    ctx.fillStyle = '#0a0f1a';
    ctx.fillRect(0, 0, w, h);

    const margin = { top: 20, right: 20, bottom: 30, left: 40 };
    const plotW = w - margin.left - margin.right;
    const plotH = h - margin.top - margin.bottom;

    function x(i) { return margin.left + (i / (steps.length - 1)) * plotW; }
    function y(v) { return margin.top + plotH - (v / maxVal) * plotH; }

    // Draw fan bands (outer to inner for correct layering)
    const bands = [
        { lo: 'p5', hi: 'p95', color: 'hsla(210, 80%, 50%, 0.12)' },
        { lo: 'p25', hi: 'p75', color: 'hsla(210, 80%, 50%, 0.25)' },
    ];

    for (const band of bands) {
        const loData = pctls[band.lo] || [];
        const hiData = pctls[band.hi] || [];
        ctx.beginPath();
        for (let i = 0; i < steps.length; i++) ctx.lineTo(x(i), y(hiData[i] || 0));
        for (let i = steps.length - 1; i >= 0; i--) ctx.lineTo(x(i), y(loData[i] || 0));
        ctx.closePath();
        ctx.fillStyle = band.color;
        ctx.fill();
    }

    // Median line
    const medData = pctls['p50'] || [];
    ctx.beginPath();
    ctx.strokeStyle = 'hsl(210, 100%, 60%)';
    ctx.lineWidth = 2;
    for (let i = 0; i < steps.length; i++) {
        if (i === 0) ctx.moveTo(x(i), y(medData[i] || 0));
        else ctx.lineTo(x(i), y(medData[i] || 0));
    }
    ctx.stroke();

    // Axes
    ctx.strokeStyle = '#334';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, margin.top + plotH);
    ctx.lineTo(margin.left + plotW, margin.top + plotH);
    ctx.stroke();

    // Labels
    ctx.fillStyle = '#667';
    ctx.font = '10px JetBrains Mono';
    for (let i = 0; i < steps.length; i += Math.max(1, Math.floor(steps.length / 6))) {
        ctx.fillText(steps[i], x(i) - 10, h - 8);
    }
    for (let v = 0; v <= maxVal; v += 1) {
        ctx.fillText(`${v}m`, 5, y(v) + 4);
    }

    ctx.fillStyle = '#889';
    ctx.font = '11px Inter';
    ctx.fillText(`Depth forecast at ${lat.toFixed(2)}, ${lng.toFixed(2)}`, margin.left, 14);
}
