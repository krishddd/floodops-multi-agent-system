/**
 * Mock data fallback for when backend is offline.
 * Provides visually rich data to demonstrate the 3D map engine.
 */
export async function getMockData(centerLat, centerLng) {
    console.log('🟡 Backend unreachable. Loading mock data...');

    // 1. Flood Depth (3D Hexagons / Columns)
    const floodDepthFeatures = [];
    for (let i = 0; i < 300; i++) {
        const offsetLat = (Math.random() - 0.5) * 0.1;
        const offsetLng = (Math.random() - 0.5) * 0.1;
        floodDepthFeatures.push({
            type: "Feature",
            geometry: { type: "Point", coordinates: [centerLng + offsetLng, centerLat + offsetLat] },
            properties: { depth_median_m: Math.random() * 6 }
        });
    }

    // 2. Population Hexbins
    const populationPoints = [];
    for (let i = 0; i < 500; i++) {
        const offsetLat = (Math.random() - 0.5) * 0.15;
        const offsetLng = (Math.random() - 0.5) * 0.15;
        populationPoints.push({
            lat: centerLat + offsetLat,
            lng: centerLng + offsetLng,
            population: Math.floor(Math.random() * 5000),
            risk_score: Math.random()
        });
    }

    // 3. Evacuation Arcs
    const evacuationRoutes = [];
    for (let i = 0; i < 50; i++) {
        const origin = [centerLng + (Math.random() - 0.5) * 0.05, centerLat + (Math.random() - 0.5) * 0.05];
        const dest = [centerLng + (Math.random() > 0.5 ? 0.1 : -0.1), centerLat + (Math.random() > 0.5 ? 0.1 : -0.1)];
        evacuationRoutes.push({ origin, dest, population: Math.floor(Math.random() * 2000) });
    }

    // 4. Glacial Lakes
    const glacialLakes = {
        type: "FeatureCollection",
        features: [{
            type: "Feature",
            geometry: {
                type: "Polygon",
                coordinates: [[[centerLng + 0.1, centerLat + 0.1], [centerLng + 0.12, centerLat + 0.1], [centerLng + 0.11, centerLat + 0.12], [centerLng + 0.1, centerLat + 0.1]]]
            },
            properties: { volume_m3: 5000000, integrity: 0.2 }
        }]
    };

    // 5. Sensors
    const sensors = {
        type: "FeatureCollection",
        features: [
            { type: "Feature", geometry: { type: "Point", coordinates: [centerLng, centerLat] }, properties: { status: 'critical' } },
            { type: "Feature", geometry: { type: "Point", coordinates: [centerLng + 0.05, centerLat - 0.05] }, properties: { status: 'elevated' } },
        ]
    };

    return {
        floodZones: null, // Omitted for clarity
        floodDepth: { type: "FeatureCollection", features: floodDepthFeatures },
        population: populationPoints,
        evacuation: evacuationRoutes,
        spaghetti: [], // Omitted
        sensors: sensors,
        glacialLakes: glacialLakes
    };
}
