"""
Day-of-year discharge climatology — real seasonal anomaly detection.

Built from the multi-decade GloFAS reanalysis (already served keyless and
24h-cached by ``OpenMeteoConnector.get_historical_discharge``). For each day
of year we pool observations from a ±window (default 15 days, wrapping the
year boundary) across all years, then summarize mean/std/percentiles.

A live forecast trace is scored against this seasonal baseline: the z-score
says "how unusual is this discharge FOR THIS TIME OF YEAR" — monsoon flows
that are normal in July would be a 5σ anomaly in January. This replaces the
mock gauge generator in SentinelAgent with real statistics (deterministic,
never LLM-gated; mock kept as fallback).

Performance: one pure-Python pass over ~15k daily values builds the pooled
index; per-basin results are memoized by the caller for 24h (same pattern as
the v3 return-period threshold cache). No numpy required.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

#: Minimum usable years before a climatology is considered defensible.
MIN_YEARS_REQUIRED = 10


@dataclass
class DayClimatology:
    """Seasonal baseline for one day of year (pooled over ±window, all years)."""

    mean: float
    std: float
    p90: float
    n: int


def _day_of_year(date_str: str) -> int | None:
    """ISO date → day-of-year 1..366 (None on parse failure)."""
    try:
        from datetime import date

        return date.fromisoformat(str(date_str)[:10]).timetuple().tm_yday
    except (ValueError, TypeError):
        return None


def build_climatology(
    times: list[str], values: list[float], window_days: int = 15
) -> dict[int, DayClimatology] | None:
    """Pool a daily series into per-day-of-year seasonal baselines.

    Returns None when the record spans fewer than ``MIN_YEARS_REQUIRED``
    distinct years (refused, never faked).
    """
    by_doy: dict[int, list[float]] = {}
    years: set[str] = set()
    for t, v in zip(times, values, strict=False):
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        doy = _day_of_year(t)
        if doy is None:
            continue
        years.add(str(t)[:4])
        by_doy.setdefault(doy, []).append(float(v))
    if len(years) < MIN_YEARS_REQUIRED:
        return None

    out: dict[int, DayClimatology] = {}
    for doy in range(1, 367):
        pooled: list[float] = []
        for off in range(-window_days, window_days + 1):
            d = (doy - 1 + off) % 366 + 1  # wrap the year boundary
            pooled.extend(by_doy.get(d, []))
        if len(pooled) < 5:
            continue
        pooled.sort()
        out[doy] = DayClimatology(
            mean=statistics.fmean(pooled),
            std=max(statistics.pstdev(pooled), 1e-6),
            p90=pooled[min(len(pooled) - 1, int(0.9 * len(pooled)))],
            n=len(pooled),
        )
    return out or None


def seasonal_zscores(
    forecast_times: list[str],
    forecast_values: list[float],
    climatology: dict[int, DayClimatology],
) -> list[tuple[str, float, float]]:
    """Score a forecast trace against the seasonal baseline.

    Returns ``[(date, value, z)]`` for every scorable day — z is how many
    seasonal standard deviations the forecast sits above (positive) or below
    (negative) the day-of-year mean.
    """
    scored: list[tuple[str, float, float]] = []
    for t, v in zip(forecast_times, forecast_values, strict=False):
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        doy = _day_of_year(t)
        if doy is None or doy not in climatology:
            continue
        c = climatology[doy]
        scored.append((str(t), float(v), (float(v) - c.mean) / c.std))
    return scored
