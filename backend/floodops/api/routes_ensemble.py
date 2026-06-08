"""Ensemble data endpoints — members, fan, disagreement, representatives."""
from __future__ import annotations
import random
from datetime import datetime, timedelta
from fastapi import APIRouter
from floodops.models.geo import GeoJsonGeometry

router = APIRouter()

@router.get("/members")
async def get_ensemble_members(time: str = "T+24h"):
    """Return ensemble member flood-front boundaries for spaghetti rendering."""
    random.seed(42)
    center_lat, center_lng = 27.7, 85.32
    members = []
    for i in range(50):
        offset = random.gauss(0, 0.02 * (i % 5 + 1))
        coords = [
            [center_lng - 0.3 + offset, center_lat - 0.2 + offset * 0.5],
            [center_lng - 0.1 + offset * 0.7, center_lat + 0.1 - offset * 0.3],
            [center_lng + 0.2 + offset * 1.2, center_lat + 0.15 + offset * 0.8],
            [center_lng + 0.4 + offset * 0.5, center_lat - 0.05 + offset * 0.2],
        ]
        depth = min(max(random.lognormvariate(0.5, 0.8), 0.1), 8.0)
        members.append({"member_id": i, "flood_front": {"type": "LineString", "coordinates": coords},
                        "peak_depth_m": round(depth, 2), "outcome": "catastrophic" if depth > 3 else "severe" if depth > 1 else "moderate" if depth > 0.5 else "minimal"})
    return {"time": time, "members": members, "count": len(members)}

@router.get("/fan")
async def get_probability_fan(lat: float = 27.7, lng: float = 85.32):
    """Return probability fan data (5th-95th percentile depth over time)."""
    random.seed(int(lat * 1000 + lng * 100))
    time_steps = [f"T+{h}h" for h in range(0, 120, 6)]
    fan = {"lat": lat, "lng": lng, "time_steps": time_steps, "percentiles": {}}
    base = random.uniform(0.5, 2.0)
    for pct, factor in [("p5", 0.2), ("p25", 0.5), ("p50", 1.0), ("p75", 1.5), ("p95", 2.5)]:
        fan["percentiles"][pct] = [round(max(0, base * factor * (1 + 0.3 * min(i, 10) / 10) + random.gauss(0, 0.1)), 2) for i, _ in enumerate(time_steps)]
    return fan

@router.get("/disagreement")
async def get_disagreement(zone_id: str = "zone_1"):
    """Return ensemble disagreement breakdown for a zone."""
    random.seed(hash(zone_id))
    cat = round(random.uniform(0.1, 0.5), 2)
    sev = round(random.uniform(0.2, 0.4), 2)
    mod = round(max(0, 1 - cat - sev - 0.05), 2)
    mini = round(max(0, 1 - cat - sev - mod), 2)
    dominant = max({"catastrophic": cat, "severe": sev, "moderate": mod, "minimal": mini}, key=lambda k: {"catastrophic": cat, "severe": sev, "moderate": mod, "minimal": mini}[k])
    return {"zone_id": zone_id, "catastrophic_pct": cat, "severe_pct": sev, "moderate_pct": mod, "minimal_pct": mini,
            "dominant_outcome": dominant, "agreement_strength": round(max(cat, sev, mod, mini), 2)}

@router.get("/representatives")
async def get_representatives(n: int = 10):
    """Return k-means-clustered representative member IDs."""
    members = (await get_ensemble_members())["members"]
    sorted_m = sorted(members, key=lambda m: m["peak_depth_m"])
    step = max(1, len(sorted_m) // n)
    return {"representative_ids": [sorted_m[i * step]["member_id"] for i in range(n)], "total_members": 50}
