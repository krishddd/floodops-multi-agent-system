"""Timeline frame endpoints for scrubber playback."""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from fastapi import APIRouter
from floodops.api.app import get_state

router = APIRouter()

@router.get("/frames")
async def get_timeline_frames(start: str = "-72h", end: str = "+240h", step: str = "6h"):
    """Return forecast snapshots for timeline scrubber animation."""
    random.seed(111)
    step_hours = int(step.replace("h", ""))
    start_h = int(start.replace("h", ""))
    end_h = int(end.replace("h", ""))
    now = datetime.utcnow()

    frames = []
    for h in range(start_h, end_h + 1, step_hours):
        t = now + timedelta(hours=h)
        is_future = h > 0
        progress = min(1.0, max(0.0, (h - start_h) / max(1, end_h - start_h)))

        # Flood extent grows, peaks, then shrinks
        peak_offset = 24  # flood peaks at T+24h
        dist_from_peak = abs(h - peak_offset)
        intensity = max(0.0, 1.0 - dist_from_peak / 72)

        frames.append({
            "time": t.isoformat() + "Z",
            "relative": f"T{h:+d}h",
            "is_forecast": is_future,
            "max_probability": round(min(0.95, intensity * 0.95 + random.gauss(0, 0.05)), 2),
            "pop_at_risk": int(intensity * 25000 + random.gauss(0, 500)),
            "flood_extent_km2": round(intensity * 45 + random.gauss(0, 3), 1),
            "peak_depth_m": round(intensity * 3.5 + random.gauss(0, 0.3), 1),
            "phase": _phase_for_hour(h),
            "ensemble_spread": round(0.2 + abs(h) * 0.01, 2) if is_future else 0.1,
        })

    return {"frames": frames, "frame_count": len(frames), "step_hours": step_hours}


@router.get("/phase-transitions")
async def get_phase_transitions():
    """Return timestamps and justifications for phase changes."""
    state = get_state()
    transitions = state.get("phase_transitions", [])
    return [t.model_dump() if hasattr(t, "model_dump") else t for t in transitions]


@router.get("/range")
async def get_timeline_range():
    now = datetime.utcnow()
    return {
        "earliest": (now - timedelta(hours=72)).isoformat() + "Z",
        "latest": (now + timedelta(hours=240)).isoformat() + "Z",
        "now": now.isoformat() + "Z",
    }


def _phase_for_hour(h: int) -> str:
    if h < -48: return "00_MONITORING"
    elif h < -24: return "01_ELEVATED"
    elif h < -6: return "02_IMMINENT"
    elif h < 0: return "03_EVACUATION"
    elif h < 24: return "04_ACTIVE"
    elif h < 336: return "05_POST_FLOOD"
    else: return "06_RECOVERY"
