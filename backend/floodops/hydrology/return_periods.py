"""
Flood-frequency analysis — per-basin return-period discharge thresholds.

Replaces the dev-only ``RETURN_PERIOD_DEPTH_THRESHOLDS_M`` constants with real,
basin-specific thresholds computed from the historical discharge record, the
way Nearing et al. (Nature 627, 2024) derive per-gauge return-period events
(USGS Bulletin 17B framing). We use Weibull plotting positions on annual maxima
with log-space interpolation — a standard, dependency-free flood-frequency fit
that is robust for the 1–10-yr return periods the paper reports on.

All functions are pure and deterministic so they are fully testable offline and
safe to drive routing (never LLM-gated).
"""

from __future__ import annotations

import math

#: Return periods (years) the paper frames skill by.
DEFAULT_RETURN_PERIODS: tuple[int, ...] = (1, 2, 5, 10)

#: Minimum years of annual maxima for a defensible frequency fit. Bulletin 17B
#: recommends 10+; below this the fit is refused (callers fall back to mocks).
MIN_YEARS_REQUIRED: int = 10


def annual_maxima(times: list[str], values: list[float]) -> dict[int, float]:
    """Reduce a daily series to the maximum value per calendar year.

    ``times`` are ISO date strings (``YYYY-MM-DD...``); entries with a None or
    non-finite value are skipped. Returns ``{year: max_value}``.
    """
    maxima: dict[int, float] = {}
    for t, v in zip(times, values, strict=False):
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        try:
            year = int(str(t)[:4])
        except (ValueError, TypeError):
            continue
        if year not in maxima or v > maxima[year]:
            maxima[year] = float(v)
    return maxima


def compute_return_period_thresholds(
    maxima: list[float],
    return_periods: tuple[int, ...] = DEFAULT_RETURN_PERIODS,
) -> dict[int, float] | None:
    """Fit return-period thresholds from a series of annual maxima.

    Weibull plotting positions: rank the ``n`` annual maxima descending; the
    ``i``-th largest has exceedance probability ``i/(n+1)`` and hence empirical
    return period ``(n+1)/i`` years. Thresholds for the requested return
    periods are read off this curve by linear interpolation in
    ``(log T, log Q)`` space, the standard treatment for skewed flood peaks.

    Return periods beyond the empirical range are clamped to the endpoints
    rather than extrapolated (honest: a 40-yr record supports a 10-yr estimate,
    not a 500-yr one). Returns None when there are fewer than
    ``MIN_YEARS_REQUIRED`` usable years or the record is degenerate (all zero).
    """
    clean = sorted(
        (m for m in maxima if m is not None and math.isfinite(m) and m >= 0),
        reverse=True,
    )
    n = len(clean)
    if n < MIN_YEARS_REQUIRED or clean[0] <= 0:
        return None

    # Empirical curve: (return period T_i, discharge Q_i), T descending in i.
    eps = 1e-9
    curve = [((n + 1) / (i + 1), max(q, eps)) for i, q in enumerate(clean)]
    log_t = [math.log(t) for t, _ in curve]
    log_q = [math.log(q) for _, q in curve]

    thresholds: dict[int, float] = {}
    for rp in return_periods:
        lt = math.log(max(rp, 1))
        if lt >= log_t[0]:  # beyond the largest empirical T → clamp
            q = log_q[0]
        elif lt <= log_t[-1]:  # below the smallest empirical T → clamp
            q = log_q[-1]
        else:
            # log_t is strictly decreasing; find the bracketing segment.
            q = log_q[-1]
            for j in range(len(log_t) - 1):
                hi, lo = log_t[j], log_t[j + 1]
                if lo <= lt <= hi:
                    frac = (lt - lo) / (hi - lo) if hi > lo else 0.0
                    q = log_q[j + 1] + frac * (log_q[j] - log_q[j + 1])
                    break
        thresholds[rp] = round(math.exp(q), 2)
    return thresholds


def classify_return_period(
    peak: float, thresholds: dict[int, float]
) -> int | None:
    """Largest return period whose threshold ``peak`` meets or exceeds.

    Returns None when the peak is below every threshold (sub-1-yr event).
    """
    best: int | None = None
    for rp in sorted(thresholds):
        if peak >= thresholds[rp]:
            best = rp
    return best
