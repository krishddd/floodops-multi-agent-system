/** Keyframe interpolation between forecast snapshots. */
export function buildKeyframes(frames) {
    return frames.map((f, i) => ({ index: i, time: f.time, relative: f.relative, data: f }));
}
