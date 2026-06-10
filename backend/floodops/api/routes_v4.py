"""
v4 routes — verification skill, basin thresholds, GDACS overlay, CAP export.

All routes serve live data when present and degrade honestly (labelled
cold-start / empty payloads) — never a 404 surprise for the frontend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from floodops.config import (
    BASIN_CENTER_LAT,
    BASIN_CENTER_LNG,
    RETURN_PERIOD_BASE_F1,
)

router = APIRouter()


def _state() -> dict[str, Any]:
    from floodops.api.app import _app_state

    return _app_state


@router.get("/verification/skill")
async def verification_skill() -> dict[str, Any]:
    """Measured forecast skill (paper's ±2-day F1) or the labelled prior.

    Cold-start contract: with fewer than VERIFICATION_MIN_SAMPLES matured
    samples this returns 200 with ``status: cold_start`` — never an error.
    """
    verifier = _state().get("verifier")
    if verifier is None:
        return {"status": "cold_start", "samples": 0,
                "prior": RETURN_PERIOD_BASE_F1,
                "last_run_ok": None, "last_error": "verifier not running"}
    return verifier.skill()


@router.get("/basin/thresholds")
async def basin_thresholds(lat: float = BASIN_CENTER_LAT,
                           lng: float = BASIN_CENTER_LNG) -> dict[str, Any]:
    """Per-basin return-period discharge thresholds (v3 engine, keyless).

    Fit from the 1984→present GloFAS reanalysis via Weibull plotting
    positions; refused (null) below 10 years of record.
    """
    from floodops.hydrology.return_periods import (
        annual_maxima,
        compute_return_period_thresholds,
    )

    connector = _state().get("connectors", {}).get("openmeteo")
    if connector is None:
        return {"lat": lat, "lng": lng, "thresholds_m3s": None,
                "note": "connector unavailable"}
    hist = await connector.get_historical_discharge(lat, lng)
    if not hist:
        return {"lat": lat, "lng": lng, "thresholds_m3s": None,
                "note": "historical record unavailable"}
    maxima = annual_maxima(hist.get("time", []), hist.get("discharge", []))
    fit = compute_return_period_thresholds(list(maxima.values()))
    return {
        "lat": lat, "lng": lng,
        "record_years": len(maxima),
        "thresholds_m3s": fit,
        "method": ("Weibull plotting positions on annual maxima (Bulletin 17B "
                   "framing; Nearing et al. 2024, DOI 10.1038/s41586-024-07145-1)"),
    }


@router.get("/hazards/gdacs")
async def gdacs_events() -> dict[str, Any]:
    """Live GDACS flood events for the map overlay (keyless)."""
    gdacs = _state().get("connectors", {}).get("gdacs")
    if gdacs is None:
        return {"events": [], "note": "connector unavailable"}
    events = await gdacs.get_flood_events()
    return {"events": events or [],
            "live": events is not None,
            "attribution": "GDACS (EC JRC / UN OCHA) — research use"}


@router.get("/hazards/googleflood")
async def googleflood_status() -> dict[str, Any]:
    """Latest Google Flood Forecasting statuses for the basin (v5, key-gated).

    The operational Nature-2024 model API. Serves an honest ``available:
    false`` payload until GOOGLE_FLOOD_API_KEY is configured.
    """
    from floodops.models.geo import BBox

    conn = _state().get("connectors", {}).get("googleflood")
    if conn is None or not getattr(conn, "available", False):
        return {"available": False, "statuses": [],
                "note": ("set GOOGLE_FLOOD_API_KEY (waitlist: "
                         "support.google.com/flood-hub/answer/16364306)")}
    from floodops.config import BASIN_BBOX_HALF_DEG

    bbox = BBox(
        south=BASIN_CENTER_LAT - BASIN_BBOX_HALF_DEG,
        west=BASIN_CENTER_LNG - BASIN_BBOX_HALF_DEG,
        north=BASIN_CENTER_LAT + BASIN_BBOX_HALF_DEG,
        east=BASIN_CENTER_LNG + BASIN_BBOX_HALF_DEG,
    )
    statuses = await conn.get_flood_status(bbox)
    return {"available": True, "statuses": statuses or [],
            "live": statuses is not None,
            "attribution": ("Google Flood Forecasting API, CC BY 4.0 "
                            "(Nearing et al. 2024)")}


@router.get("/alerts/{alert_id}/cap.xml")
async def alert_cap_xml(alert_id: str) -> Response:
    """A dispatched alert rendered as CAP 1.2 XML (agency dissemination)."""
    from floodops.models.cap import to_cap_xml

    dispatch: dict[str, Any] | None = None
    store = _state().get("store")
    if store is not None and store.enabled:
        dispatch = await store.get_alert(alert_id)
    if dispatch is None:
        # Fall back to live state (cold store / persistence disabled).
        for d in _state().get("flood_state", {}).get("alert_dispatches", []) or []:
            data = d if isinstance(d, dict) else d.model_dump()
            if str(data.get("dispatch_id")) == alert_id:
                dispatch = data
                break
    if dispatch is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return Response(content=to_cap_xml(dispatch), media_type="application/xml")
