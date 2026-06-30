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


# ── v5: full Google Flood Forecasting surface (key-gated, read-only) ──────

_GF_ATTR = "Google Flood Forecasting API, CC BY 4.0 (Nearing et al. 2024)"
_GF_NOTE = ("set FLOODS_API_KEY or GOOGLE_FLOOD_API_KEY (waitlist: "
            "support.google.com/flood-hub/answer/16364306)")


def _googleflood():
    """The connector if keyed & available, else None."""
    conn = _state().get("connectors", {}).get("googleflood")
    if conn is None or not getattr(conn, "available", False):
        return None
    return conn


def _basin_bbox():
    from floodops.config import BASIN_BBOX_HALF_DEG
    from floodops.models.geo import BBox

    return BBox(
        south=BASIN_CENTER_LAT - BASIN_BBOX_HALF_DEG,
        west=BASIN_CENTER_LNG - BASIN_BBOX_HALF_DEG,
        north=BASIN_CENTER_LAT + BASIN_BBOX_HALF_DEG,
        east=BASIN_CENTER_LNG + BASIN_BBOX_HALF_DEG,
    )


@router.get("/hazards/googleflood/forecasts")
async def googleflood_forecasts(days_back: int = 7) -> dict[str, Any]:
    """Quantitative LSTM forecasts (discharge/level, multiple lead times) for
    the basin's gauges — Google's Hydrology Model API. Honest unavailable
    until keyed."""
    import datetime as _dt

    conn = _googleflood()
    if conn is None:
        return {"available": False, "forecasts": {}, "note": _GF_NOTE}
    gauges = await conn.get_gauges(_basin_bbox())
    gauge_ids = [g.get("gaugeId") for g in (gauges or []) if g.get("gaugeId")]
    if not gauge_ids:
        return {"available": True, "forecasts": {}, "gauges": 0,
                "note": "no gauges in basin bbox", "attribution": _GF_ATTR}
    start = (_dt.datetime.utcnow() - _dt.timedelta(days=days_back)).strftime("%Y-%m-%d")
    end = (_dt.datetime.utcnow() + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    forecasts = await conn.query_gauge_forecasts(gauge_ids, start, end)
    return {"available": True, "gauges": len(gauge_ids),
            "window": {"issued_time_start": start, "issued_time_end": end},
            "forecasts": forecasts or {}, "attribution": _GF_ATTR}


@router.get("/basin/google-thresholds")
async def googleflood_thresholds() -> dict[str, Any]:
    """Google's OFFICIAL gauge-model thresholds (warning/danger/extreme) for
    the basin's gauges — an independent cross-check against our Weibull-fitted
    return-period thresholds (see /basin/thresholds). Honest unavailable until
    keyed."""
    conn = _googleflood()
    if conn is None:
        return {"available": False, "gauge_models": [], "note": _GF_NOTE}
    gauges = await conn.get_gauges(_basin_bbox())
    gauge_ids = [g.get("gaugeId") for g in (gauges or []) if g.get("gaugeId")]
    if not gauge_ids:
        return {"available": True, "gauge_models": [], "gauges": 0,
                "note": "no gauges in basin bbox", "attribution": _GF_ATTR}
    models = await conn.get_gauge_models(gauge_ids)
    return {"available": True, "gauges": len(gauge_ids),
            "gauge_models": models or [], "attribution": _GF_ATTR}


@router.get("/hazards/googleflood/significant-events")
async def googleflood_significant_events(region_code: str = "") -> dict[str, Any]:
    """Clustered major flood events (area + population impact) — the pulsing
    red circles on Flood Hub. Honest unavailable until keyed."""
    conn = _googleflood()
    if conn is None:
        return {"available": False, "events": [], "note": _GF_NOTE}
    events = await conn.get_significant_events(region_code=region_code)
    return {"available": True, "events": events or [],
            "live": events is not None, "attribution": _GF_ATTR}


@router.get("/hazards/googleflood/flash-floods")
async def googleflood_flash_floods(region_code: str = "") -> dict[str, Any]:
    """Urban flash-flood events (24h probability per urban region). Honest
    unavailable until keyed."""
    conn = _googleflood()
    if conn is None:
        return {"available": False, "events": [], "note": _GF_NOTE}
    events = await conn.get_flash_floods(region_code=region_code)
    return {"available": True, "events": events or [],
            "live": events is not None, "attribution": _GF_ATTR}


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
