/**
 * deck.gl layer definitions for FloodOps.
 * 7 layers — each chosen for maximum visual impact of its data type.
 */
import { GeoJsonLayer, ScatterplotLayer, ArcLayer, PathLayer, ColumnLayer, PolygonLayer } from '@deck.gl/layers';
import { HexagonLayer } from '@deck.gl/aggregation-layers';
import { getState } from '../state.js';

const RISK_COLORS = {
    CRITICAL: [220, 40, 40],   // red
    HIGH:     [230, 120, 30],  // orange
    MEDIUM:   [230, 200, 50],  // amber
    LOW:      [60, 180, 80],   // green
};

function riskToColor(score) {
    if (score > 0.8) return [220, 40, 40];
    if (score > 0.6) return [230, 120, 30];
    if (score > 0.3) return [230, 200, 50];
    return [60, 180, 80];
}

function depthToColor(depth) {
    const t = Math.min(depth / 5, 1);
    return [30 + 50 * (1 - t), 150 + 100 * (1 - t), 220, 200];
}

export function buildLayers(data, layerState) {
    const layers = [];

    // 1. FLOOD ZONES — GeoJsonLayer
    if (layerState.floodZones?.visible && data.floodZones) {
        layers.push(new GeoJsonLayer({
            id: 'flood-zones',
            data: data.floodZones,
            filled: true,
            stroked: true,
            getFillColor: f => {
                const c = riskToColor(f.properties.risk_score);
                const alpha = Math.floor((f.properties.confidence || 0.5) * 200 + 55);
                return [...c, alpha];
            },
            getLineColor: [255, 255, 255, 100],
            getLineWidth: f => Math.max(1, (f.properties.ensemble_agreement || 25) / 10),
            lineWidthUnits: 'pixels',
            opacity: layerState.floodZones.opacity,
            pickable: true,
            transitions: { getFillColor: 600 },
        }));
    }

    // 2. FLOOD DEPTH — ColumnLayer (extruded 3D)
    if (layerState.floodDepth?.visible && data.floodDepth) {
        const features = data.floodDepth?.features || [];
        layers.push(new ColumnLayer({
            id: 'flood-depth',
            data: features,
            diskResolution: 6,
            radius: 40,
            extruded: true,
            elevationScale: 100,
            getPosition: f => f.geometry.coordinates,
            getElevation: f => f.properties.depth_median_m * 100,
            getFillColor: f => depthToColor(f.properties.depth_median_m),
            opacity: layerState.floodDepth.opacity,
            pickable: true,
            transitions: { getElevation: 800 },
        }));
    }

    // 3. POPULATION AT RISK — HexagonLayer
    if (layerState.population?.visible && data.population) {
        layers.push(new HexagonLayer({
            id: 'population-risk',
            data: data.population,
            getPosition: d => [d.lng, d.lat],
            getElevationWeight: d => d.population,
            getColorWeight: d => d.risk_score,
            elevationScale: 50,
            radius: 200,
            extruded: true,
            colorRange: [[65, 182, 96], [230, 200, 50], [230, 120, 30], [220, 40, 40]],
            opacity: layerState.population.opacity,
            pickable: true,
        }));
    }

    // 4. EVACUATION FLOWS — ArcLayer
    if (layerState.evacuation?.visible && data.evacuation) {
        layers.push(new ArcLayer({
            id: 'evacuation-arcs',
            data: data.evacuation,
            getSourcePosition: d => d.origin,
            getTargetPosition: d => d.dest,
            getSourceColor: [220, 40, 40, 200],
            getTargetColor: [60, 180, 80, 200],
            getWidth: d => Math.max(2, (d.population || 1000) / 1000),
            widthUnits: 'pixels',
            opacity: layerState.evacuation.opacity,
            pickable: true,
        }));
    }

    // 5. ENSEMBLE SPAGHETTI — PathLayer
    if (layerState.spaghetti?.visible && data.spaghetti) {
        const COLORS = [[255,107,107],[255,159,67],[254,202,87],[29,209,161],[72,219,251],[52,172,224],[112,111,211],[223,142,247],[255,99,72],[75,207,157]];
        layers.push(new PathLayer({
            id: 'ensemble-spaghetti',
            data: data.spaghetti,
            getPath: d => d.flood_front.coordinates,
            getColor: (d, { index }) => [...COLORS[index % COLORS.length], 60],
            getWidth: 2,
            widthUnits: 'pixels',
            opacity: layerState.spaghetti.opacity,
            pickable: false,
        }));
    }

    // 6. SENSORS — ScatterplotLayer
    if (layerState.sensors?.visible && data.sensors) {
        const features = data.sensors?.features || [];
        layers.push(new ScatterplotLayer({
            id: 'sensors',
            data: features,
            getPosition: f => f.geometry.coordinates,
            getFillColor: f => {
                const s = f.properties.status;
                if (s === 'critical') return [220, 40, 40, 255];
                if (s === 'elevated') return [230, 200, 50, 255];
                return [60, 180, 80, 255];
            },
            getRadius: f => f.properties.status === 'critical' ? 500 : 300,
            radiusUnits: 'meters',
            stroked: true,
            getLineColor: [255, 255, 255, 150],
            getLineWidth: 2,
            lineWidthUnits: 'pixels',
            opacity: layerState.sensors.opacity,
            pickable: true,
            transitions: { getRadius: 500 },
        }));
    }

    // 7. GLACIAL LAKES — GeoJsonLayer with extrusion
    if (layerState.glacialLakes?.visible && data.glacialLakes) {
        layers.push(new GeoJsonLayer({
            id: 'glacial-lakes',
            data: data.glacialLakes,
            filled: true,
            stroked: true,
            extruded: true,
            getElevation: f => (f.properties.volume_m3 || 1e6) / 1e5,
            getFillColor: f => {
                const i = f.properties.integrity;
                if (i < 0.3) return [220, 40, 40, 200];
                if (i < 0.7) return [230, 200, 50, 180];
                return [60, 180, 80, 160];
            },
            getLineColor: [255, 255, 255, 120],
            getLineWidth: 2,
            lineWidthUnits: 'pixels',
            opacity: layerState.glacialLakes.opacity,
            pickable: true,
        }));
    }

    return layers;
}
