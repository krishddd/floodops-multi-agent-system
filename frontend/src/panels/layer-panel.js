/** Layer panel — wire checkbox/slider to state and deck.gl. */
import { updateLayer, getState } from '../state.js';

export function initLayerPanel(onUpdate) {
    const checkboxes = document.querySelectorAll('.layer-item input[type="checkbox"]');
    const sliders = document.querySelectorAll('.opacity-slider');

    checkboxes.forEach(cb => {
        cb.addEventListener('change', () => {
            const layerName = cb.closest('.layer-item')?.dataset.layer;
            if (layerName) {
                updateLayer(layerName, { visible: cb.checked });
                if (onUpdate) onUpdate();
            }
        });
    });

    sliders.forEach(slider => {
        slider.addEventListener('input', () => {
            const layerName = slider.dataset.layer;
            if (layerName) {
                updateLayer(layerName, { opacity: parseInt(slider.value) / 100 });
                if (onUpdate) onUpdate();
            }
        });
    });
}

export function renderDataCadence(badges) {
    const container = document.getElementById('data-cadence');
    if (!container || !badges) return;
    container.innerHTML = '<div class="panel-title" style="margin-bottom:8px">Data Sources</div>' +
        badges.map(b => `<div class="cadence-row"><span class="emoji">${b.emoji}</span><span class="source">${b.source}</span><span class="time">${b.cadence}</span></div>`).join('');
}
