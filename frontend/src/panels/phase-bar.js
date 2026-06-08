/** Phase bar and metrics update logic. */
const PHASE_NAMES = { '00': 'MONITORING', '01': 'ELEVATED', '02': 'IMMINENT', '03': 'EVACUATION', '04': 'ACTIVE', '05': 'POST_FLOOD', '06': 'RECOVERY' };
const PHASE_COLORS = { '00': 'var(--accent-blue)', '01': 'var(--risk-moderate)', '02': 'var(--risk-severe)', '03': 'var(--risk-critical)', '04': 'var(--risk-emergency)', '05': 'var(--accent-purple)', '06': 'var(--risk-minimal)' };

export function updatePhaseBar(phase) {
    const num = typeof phase === 'string' ? phase.split('_')[0] : '00';
    const dots = document.querySelectorAll('.phase-dot');
    const connectors = document.querySelectorAll('.phase-connector');
    const phaseNum = parseInt(num);

    dots.forEach((dot, i) => {
        dot.classList.remove('active', 'completed', 'alert');
        const dotPhase = parseInt(dot.dataset.phase);
        if (dotPhase < phaseNum) dot.classList.add('completed');
        else if (dotPhase === phaseNum) {
            dot.classList.add('active');
            if (phaseNum >= 3) dot.classList.add('alert');
        }
    });

    connectors.forEach((c, i) => {
        c.style.background = i < phaseNum ? 'var(--risk-minimal)' : 'var(--glass-border)';
    });
}

export function updateMetrics(data) {
    const pop = document.getElementById('metric-pop');
    const eta = document.getElementById('metric-eta');
    const prob = document.getElementById('metric-prob');
    if (pop) pop.textContent = data.pop_at_risk?.toLocaleString() || '—';
    if (eta) eta.textContent = data.relative || data.peak_eta || '—';
    if (prob) {
        const p = data.max_probability || 0;
        prob.textContent = `${Math.round(p * 100)}%`;
        prob.style.color = p > 0.8 ? 'var(--risk-critical)' : p > 0.5 ? 'var(--risk-severe)' : 'var(--text-primary)';
    }
}
