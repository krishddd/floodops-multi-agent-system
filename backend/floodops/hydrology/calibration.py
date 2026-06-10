"""
Runoff-model calibration against the reanalysis (v5).

The v4 runoff ensemble is physically motivated but uncalibrated: its absolute
discharge depends on uncertain defaults (runoff coefficient, recession k,
effective area). This module closes the documented v5 gap with the simplest
defensible calibration — a single per-basin **scale factor**:

  1. Route each historical year's daily precipitation (Open-Meteo archive
     reanalysis, keyless) through the SAME linear-reservoir model the live
     ensemble uses.
  2. Compare routed annual maxima against observed annual maxima from the
     GloFAS discharge reanalysis (same record the return-period thresholds
     are fitted from).
  3. ``scale = median(observed_max / routed_max)`` across paired years —
     median for robustness against individual bad years.

The live ensemble multiplies each member's routed peak by this scale before
depth conversion, so member discharge lands in the same regime as the fitted
thresholds. HONEST FRAMING: this is bias correction of the magnitude only —
not parameter estimation (timing/shape stay uncalibrated; full calibration
would fit k and the runoff coefficient jointly, a v6 item).

Refusal rule: fewer than ``MIN_YEARS_REQUIRED`` paired years (or degenerate
routed maxima) → None, and callers keep the uncalibrated behaviour. Pure
Python, fully offline-testable.
"""

from __future__ import annotations

import math
import statistics

from floodops.hydrology.runoff import route_linear_reservoir

MIN_YEARS_REQUIRED = 10

#: Clamp for pathological records: scale outside this range is refused
#: (indicates the model regime is wrong for the basin, not a bias).
SCALE_BOUNDS = (0.01, 100.0)


def _by_year(times: list[str], values: list[float]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for t, v in zip(times, values, strict=False):
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        try:
            year = int(str(t)[:4])
        except (ValueError, TypeError):
            continue
        out.setdefault(year, []).append(float(v))
    return out


def calibrate_runoff_scale(
    precip_times: list[str],
    precip_values: list[float],
    discharge_times: list[str],
    discharge_values: list[float],
    area_km2: float,
    recession_k: float = 0.3,
) -> dict | None:
    """Fit the per-basin discharge scale factor (see module docstring).

    Returns ``{"scale", "paired_years", "ratio_p25", "ratio_p75"}`` or None
    when the record is too short / degenerate (callers stay uncalibrated).
    Years with fewer than 300 daily values on either side are skipped
    (incomplete years bias annual maxima low).
    """
    precip_years = _by_year(precip_times, precip_values)
    discharge_years = _by_year(discharge_times, discharge_values)

    ratios: list[float] = []
    for year in sorted(set(precip_years) & set(discharge_years)):
        p, q = precip_years[year], discharge_years[year]
        if len(p) < 300 or len(q) < 300:
            continue
        routed = route_linear_reservoir(p, area_km2, recession_k=recession_k)
        routed_max = max(routed) if routed else 0.0
        obs_max = max(q)
        if routed_max <= 0 or obs_max <= 0:
            continue
        ratios.append(obs_max / routed_max)

    if len(ratios) < MIN_YEARS_REQUIRED:
        return None
    ratios.sort()
    scale = statistics.median(ratios)
    if not (SCALE_BOUNDS[0] <= scale <= SCALE_BOUNDS[1]):
        return None
    return {
        "scale": round(scale, 4),
        "paired_years": len(ratios),
        "ratio_p25": round(ratios[len(ratios) // 4], 4),
        "ratio_p75": round(ratios[(3 * len(ratios)) // 4], 4),
    }
