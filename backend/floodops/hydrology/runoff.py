"""
Linear-reservoir rainfall–runoff routing — physically-motivated ensemble.

Replaces the pure-random mock flood ensemble with members that physically
follow the REAL Open-Meteo 7-day precipitation forcing:

  1. **Perturbation** (pinned): each member's daily precip is multiplied by a
     factor drawn ``Uniform(1 − ENSEMBLE_SPREAD, 1 + ENSEMBLE_SPREAD)``
     (default spread 0.20), RNG seeded with the member index → deterministic.
     A placeholder for a proper stochastic weather generator (v5).
  2. **Routing**: effective rainfall enters a linear reservoir
     (``Q_t = k · S_t``); time-to-peak comes from the empirical relation
     ``tp = 0.5 · sqrt(area_km2)`` hours, applied as an inflow delay.
  3. **Depth conversion**: the member's peak discharge is mapped to flood
     depth by piecewise log-linear interpolation between the basin's FITTED
     return-period discharge thresholds (v3 engine) and the configured
     return-period depth scale — so "a 5-yr discharge" produces "a 5-yr depth"
     for this basin specifically.

HONEST FRAMING: physically-motivated, NOT calibrated. ``tp`` and ``k``
(``RUNOFF_RECESSION_K``) are uncalibrated defaults documented in CLAUDE.md;
calibration against the GloFAS reanalysis is a v5 item. Streamflow is still
never an input — only precipitation drives the members; the fitted discharge
thresholds are used as a basin-specific *scale*, which is reference use.

Pure Python, deterministic given the forcing; tested offline.
"""

from __future__ import annotations

import math
import random

#: Fraction of rainfall that becomes runoff (uncalibrated default).
RUNOFF_COEFFICIENT = 0.4

#: Map return period → representative flood depth (m) used as the depth scale.
#: Mirrors config.RETURN_PERIOD_DEPTH_THRESHOLDS_M (imported lazily to avoid
#: a config dependency in this pure module — callers may pass their own).
DEFAULT_DEPTH_SCALE: dict[int, float] = {1: 0.5, 2: 1.0, 5: 2.0, 10: 3.0}

MAX_DEPTH_M = 8.0


def perturb_precip(
    daily_precip_mm: list[float], member_index: int, spread: float = 0.20
) -> list[float]:
    """Member-seeded uniform multiplicative perturbation (pinned semantics)."""
    rng = random.Random(member_index)
    factor = 1.0 - spread + 2.0 * spread * rng.random()
    return [max(0.0, p) * factor for p in daily_precip_mm]


def time_to_peak_hours(area_km2: float) -> float:
    """Empirical time-to-peak: tp = 0.5 · sqrt(area_km2) hours (uncalibrated)."""
    return 0.5 * math.sqrt(max(area_km2, 1.0))


def route_linear_reservoir(
    daily_precip_mm: list[float],
    area_km2: float,
    recession_k: float = 0.3,
    runoff_coefficient: float = RUNOFF_COEFFICIENT,
) -> list[float]:
    """Route daily rainfall through a delayed linear reservoir → m³/s per day.

    ``Q_t = k · S_t`` with storage update ``S_{t+1} = S_t + R_t − Q_t`` (all in
    mm over the basin); inflow is delayed by round(tp / 24h) whole days. The
    mm/day outflow converts to m³/s via the basin area.
    """
    k = min(max(recession_k, 0.01), 1.0)
    delay_days = round(time_to_peak_hours(area_km2) / 24.0)
    inflow = [0.0] * delay_days + [
        max(0.0, p) * runoff_coefficient for p in daily_precip_mm
    ]

    discharge_m3s: list[float] = []
    storage = 0.0
    mm_day_to_m3s = area_km2 * 1e6 * 1e-3 / 86400.0  # mm/day over area → m³/s
    for r in inflow:
        storage += r
        q_mm = k * storage
        storage -= q_mm
        discharge_m3s.append(q_mm * mm_day_to_m3s)
    return discharge_m3s


def discharge_to_depth(
    peak_discharge_m3s: float,
    discharge_thresholds_m3s: dict[int, float],
    depth_scale: dict[int, float] | None = None,
) -> float:
    """Map peak discharge → flood depth via the basin's return-period scale.

    Piecewise log-linear between (Q_rp, depth_rp) anchor points; below the
    1-yr anchor depth scales linearly toward zero, above the largest anchor it
    extrapolates linearly in the ratio (capped at MAX_DEPTH_M).
    """
    depths = depth_scale or DEFAULT_DEPTH_SCALE
    anchors = sorted(
        (q, depths[rp]) for rp, q in discharge_thresholds_m3s.items()
        if rp in depths and q > 0
    )
    if not anchors or peak_discharge_m3s <= 0:
        return 0.0
    q0, d0 = anchors[0]
    if peak_discharge_m3s <= q0:
        return round(d0 * peak_discharge_m3s / q0, 2)
    for (qa, da), (qb, db) in zip(anchors, anchors[1:], strict=False):
        if qa <= peak_discharge_m3s <= qb:
            frac = ((math.log(peak_discharge_m3s) - math.log(qa))
                    / (math.log(qb) - math.log(qa)))
            return round(da + frac * (db - da), 2)
    qn, dn = anchors[-1]
    return round(min(MAX_DEPTH_M, dn * peak_discharge_m3s / qn), 2)
