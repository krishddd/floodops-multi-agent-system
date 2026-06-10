"""
Forecast verification loop — measured skill replaces illustrative constants.

Implements the skill metric of Nearing et al., Nature 627, 559-563 (2024),
DOI 10.1038/s41586-024-07145-1 (Methods §Metrics): precision/recall/F1 over
return-period exceedance events, where a HIT means the predicted and observed
series cross their respective return-period threshold **within ±2 days** of
each other.

Mechanics (pinned in the v4 plan):
  * Every emitted flood forecast is recorded with the GloFAS forecast-mean
    trace and the basin's fitted discharge thresholds at issue time.
  * An asyncio background task (created in the FastAPI lifespan, interval
    ``VERIFICATION_JOB_INTERVAL_S``) scores matured samples (≥1 day old)
    against the GloFAS reanalysis "observations" for the overlapping days.
  * The task body is wrapped in a broad try/except — failures are logged and
    the sleep/reschedule loop continues unconditionally; ``last_run_ok`` /
    ``last_error`` are exposed for observability. The task can never silently
    die.
  * Below ``VERIFICATION_MIN_SAMPLES`` matured samples the skill route serves
    a labelled cold-start prior (``RETURN_PERIOD_BASE_F1``), never an error.

Samples live in memory and (when a store is attached, Phase 3) survive
restarts via the ``verification_samples`` table.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from floodops.config import (
    RETURN_PERIOD_BASE_F1,
    VERIFICATION_JOB_INTERVAL_S,
    VERIFICATION_MIN_SAMPLES,
)

logger = logging.getLogger(__name__)

#: Paper rule: predicted and observed crossings must be within this many days.
HIT_TOLERANCE_DAYS = 2


@dataclass
class _PendingForecast:
    forecast_id: str
    issued_at: datetime
    lat: float
    lng: float
    thresholds: dict[int, float]
    trace_times: list[str]
    trace_values: list[float]
    scored: bool = False


@dataclass
class _Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0


def _first_crossing_day(times: list[str], values: list[float],
                        threshold: float) -> str | None:
    """First date whose value meets/exceeds the threshold, else None."""
    for t, v in zip(times, values, strict=False):
        if v is not None and v >= threshold:
            return str(t)[:10]
    return None


def _days_apart(a: str, b: str) -> float:
    from datetime import date

    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def score_sample(
    predicted_times: list[str],
    predicted_values: list[float],
    observed_times: list[str],
    observed_values: list[float],
    thresholds: dict[int, float],
) -> dict[int, dict[str, int]]:
    """Per-return-period hit/miss/false-alarm for one forecast sample.

    Pure function (offline-testable). Returns
    ``{rp: {"tp": 0|1, "fp": 0|1, "fn": 0|1}}`` per the paper's ±2-day rule:
      * both cross within ±2 days → TP
      * predicted crosses, observed doesn't (or >2 days apart) → FP
      * observed crosses, predicted doesn't → FN (a >2-day-apart pair counts
        as both FP and FN, matching event-based contingency scoring)
    """
    out: dict[int, dict[str, int]] = {}
    for rp, threshold in thresholds.items():
        pred = _first_crossing_day(predicted_times, predicted_values, threshold)
        obs = _first_crossing_day(observed_times, observed_values, threshold)
        tp = fp = fn = 0
        if pred and obs:
            if _days_apart(pred, obs) <= HIT_TOLERANCE_DAYS:
                tp = 1
            else:
                fp, fn = 1, 1
        elif pred:
            fp = 1
        elif obs:
            fn = 1
        out[int(rp)] = {"tp": tp, "fp": fp, "fn": fn}
    return out


class ForecastVerifier:
    """Records issued forecasts and scores them as observations mature."""

    def __init__(self, connector: Any = None, store: Any = None) -> None:
        self._connector = connector
        self._store = store  # Phase 3: obs.store for restart-safe samples
        self._pending: list[_PendingForecast] = []
        self._counts: dict[int, _Counts] = {}
        self._samples_scored = 0
        self.last_run_ok: bool | None = None
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None

    # ── Recording (subscribed to the flood_forecasts channel) ────────

    async def record(self, channel: str, payload: Any) -> None:
        """Capture a forecast + the GloFAS trace + thresholds at issue time."""
        try:
            data = payload if isinstance(payload, dict) else payload.model_dump()
            thresholds = data.get("benchmark_discharge_thresholds_m3s")
            bbox = data.get("bbox") or {}
            if not thresholds or not bbox:
                return  # nothing scorable (no fitted thresholds for this basin)
            lat = (bbox.get("south", 0) + bbox.get("north", 0)) / 2
            lng = (bbox.get("west", 0) + bbox.get("east", 0)) / 2
            trace = (await self._connector.get_discharge_ensemble(lat, lng)
                     if self._connector else None) or {}
            sample = _PendingForecast(
                forecast_id=str(data.get("forecast_id", "")),
                issued_at=datetime.utcnow(),
                lat=lat, lng=lng,
                thresholds={int(k): float(v) for k, v in thresholds.items()},
                trace_times=list(trace.get("time", [])),
                trace_values=[v if v is not None else 0.0
                              for v in trace.get("mean", [])],
            )
            if sample.trace_times:
                self._pending.append(sample)
                if self._store is not None:
                    await self._store.save_forecast_sample(sample)
        except Exception as exc:
            logger.warning("verification record failed: %s", exc)

    # ── Background scoring loop ──────────────────────────────────────

    def start(self) -> None:
        """Create the background task (call from the FastAPI lifespan)."""
        self._task = asyncio.create_task(self._run_forever(), name="verification")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def _run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
                self.last_run_ok = True
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — must never die silently
                self.last_run_ok = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.error("verification run failed (loop continues): %s", exc)
            await asyncio.sleep(VERIFICATION_JOB_INTERVAL_S)

    async def run_once(self) -> int:
        """Score every matured (≥1 day) unscored sample. Returns #scored."""
        if self._connector is None:
            return 0
        matured = [p for p in self._pending
                   if not p.scored
                   and datetime.utcnow() - p.issued_at >= timedelta(days=1)]
        scored = 0
        for sample in matured:
            hist = await self._connector.get_historical_discharge(
                sample.lat, sample.lng
            )
            if not hist:
                continue
            issue_day = sample.issued_at.date().isoformat()
            obs_pairs = [
                (t, v) for t, v in zip(hist.get("time", []),
                                       hist.get("discharge", []), strict=False)
                if str(t)[:10] >= issue_day and v is not None
            ]
            if not obs_pairs:
                continue
            obs_t = [t for t, _ in obs_pairs]
            obs_v = [v for _, v in obs_pairs]
            # Compare only the predicted days that already have observations.
            horizon = {str(t)[:10] for t in obs_t}
            pred_pairs = [
                (t, v) for t, v in zip(sample.trace_times, sample.trace_values,
                                       strict=False)
                if str(t)[:10] in horizon
            ]
            if not pred_pairs:
                continue
            result = score_sample(
                [t for t, _ in pred_pairs], [v for _, v in pred_pairs],
                obs_t, obs_v, sample.thresholds,
            )
            for rp, c in result.items():
                agg = self._counts.setdefault(rp, _Counts())
                agg.tp += c["tp"]
                agg.fp += c["fp"]
                agg.fn += c["fn"]
            sample.scored = True
            self._samples_scored += 1
            scored += 1
            if self._store is not None:
                await self._store.save_verification_result(
                    sample.forecast_id, result
                )
        return scored

    # ── Skill summary (served by the API route) ──────────────────────

    def skill(self) -> dict[str, Any]:
        """Live measured skill, or the labelled cold-start prior."""
        base = {
            "samples": self._samples_scored,
            "min_samples": VERIFICATION_MIN_SAMPLES,
            "last_run_ok": self.last_run_ok,
            "last_error": self.last_error,
            "metric": ("precision/recall/F1 over return-period exceedance "
                       f"events, ±{HIT_TOLERANCE_DAYS}-day hit rule "
                       "(Nearing et al. 2024, DOI 10.1038/s41586-024-07145-1)"),
        }
        if self._samples_scored < VERIFICATION_MIN_SAMPLES:
            return {**base, "status": "cold_start",
                    "prior": RETURN_PERIOD_BASE_F1}
        measured: dict[int, dict[str, float]] = {}
        for rp, c in sorted(self._counts.items()):
            precision = c.tp / (c.tp + c.fp) if (c.tp + c.fp) else 0.0
            recall = c.tp / (c.tp + c.fn) if (c.tp + c.fn) else 0.0
            f1 = (2 * precision * recall / (precision + recall)
                  if (precision + recall) else 0.0)
            measured[rp] = {"precision": round(precision, 3),
                            "recall": round(recall, 3),
                            "f1": round(f1, 3),
                            "tp": c.tp, "fp": c.fp, "fn": c.fn}
        return {**base, "status": "measured", "skill": measured}
