/** Frame-by-frame animation engine. */
export function interpolateFrame(frameA, frameB, t) {
    if (!frameA || !frameB) return frameA || frameB;
    return {
        ...frameA,
        max_probability: lerp(frameA.max_probability, frameB.max_probability, t),
        pop_at_risk: Math.round(lerp(frameA.pop_at_risk, frameB.pop_at_risk, t)),
        flood_extent_km2: lerp(frameA.flood_extent_km2, frameB.flood_extent_km2, t),
        peak_depth_m: lerp(frameA.peak_depth_m, frameB.peak_depth_m, t),
    };
}
function lerp(a, b, t) { return a + (b - a) * t; }
