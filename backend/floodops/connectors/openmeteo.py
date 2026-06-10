"""
🟢 LIVE (keyless) — Open-Meteo connector.

Two free, no-key endpoints:
  * Forecast API   — paper-faithful meteorological FORCING (precipitation,
                     2-m temperature, shortwave radiation, snowfall, surface
                     pressure) → the inputs the FloodPredict ensemble is driven by.
  * Flood API      — GloFAS river-discharge ensemble percentiles → a BENCHMARK
                     REFERENCE only, never a model input.

Why the distinction: Nearing et al. (Nature 627, 2024) drive the AI flood model
from meteorological + geophysical inputs and use **no streamflow as input** (real-
time discharge isn't available in ungauged basins, and GloFAS is the benchmark the
paper beats). So ``get_meteorology()`` is the forcing the predictor consumes;
``get_discharge_ensemble()`` is kept purely as a comparison reference.

No API key required. Rate-limited free tier, so cache TTL is 900s (data updates
hourly) and every method degrades to ``None`` on failure so agents fall back to
their deterministic mock generation.
"""

from __future__ import annotations

import time
from typing import Any

from floodops.connectors.base import BaseConnector
from floodops.models.enums import DataSource
from floodops.models.geo import BBox


class OpenMeteoConnector(BaseConnector):
    """Keyless rainfall + river-discharge ensemble connector."""

    source = DataSource.ECMWF_ENSEMBLE
    expected_cadence = "hourly"
    is_mock = False

    FORECAST_BASE = "https://api.open-meteo.com/v1/forecast"
    FLOOD_BASE = "https://flood-api.open-meteo.com/v1/flood"

    def __init__(self, **kwargs: Any) -> None:
        # Hourly data → 15-min cache is plenty; default to 900s per the plan.
        kwargs.setdefault("cache_ttl_seconds", 900)
        super().__init__(**kwargs)

    async def health_check(self) -> bool:
        try:
            await self.fetch_with_retry(
                self.FORECAST_BASE,
                params={"latitude": 27.7, "longitude": 85.3, "hourly": "precipitation",
                        "forecast_days": 1},
            )
            return True
        except Exception:
            return False

    async def fetch_latest(self, bbox: BBox | None = None, **kwargs: Any) -> dict:
        """Return forcing + reference data for the centre of ``bbox`` (or Kathmandu).

        Keys:
          * ``meteorology`` — paper-faithful forcing the predictor consumes.
          * ``rainfall``    — precipitation-only summary (back-compat).
          * ``discharge``   — GloFAS ensemble, BENCHMARK REFERENCE only (not an input).
        """
        if bbox is not None:
            c = bbox.center()
            lat, lng = c.lat, c.lng
        else:
            lat, lng = 27.7, 85.3
        return {
            "meteorology": await self.get_meteorology(lat, lng),
            "rainfall": await self.get_rainfall(lat, lng),
            "discharge": await self.get_discharge_ensemble(lat, lng),
        }

    async def get_meteorology(self, lat: float, lng: float) -> dict | None:
        """Paper-faithful meteorological forcing (Nearing et al. 2024 input set).

        Fetches the Open-Meteo analogues of the paper's ECMWF IFS HRES / ERA5-Land
        variables — precipitation, 2-m temperature, shortwave radiation, snowfall,
        surface pressure — and summarises the next 72h. ``positive_degree_hours``
        is the snowmelt driver (sum of hourly temps above 0 °C), which matters for
        the Himalayan basin where melt compounds rainfall. Returns None on failure.
        """
        try:
            data = await self.fetch_with_retry(
                self.FORECAST_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "hourly": ("precipitation,temperature_2m,shortwave_radiation,"
                               "snowfall,surface_pressure"),
                    "forecast_days": 7,
                },
            )
            hourly = data.get("hourly", {})

            def _clean(key: str) -> list[float]:
                return [v for v in hourly.get(key, []) if v is not None]

            precip = _clean("precipitation")
            temp = _clean("temperature_2m")
            radiation = _clean("shortwave_radiation")
            snowfall = _clean("snowfall")
            pdh = round(sum(t for t in temp[:72] if t > 0), 1)
            return {
                "precip_total_72h_mm": round(sum(precip[:72]), 1),
                "peak_precip_mm_h": max(precip) if precip else 0.0,
                "mean_temp_c": round(sum(temp[:72]) / len(temp[:72]), 1) if temp else None,
                "positive_degree_hours_72h": pdh,
                "snowfall_total_72h_cm": round(sum(snowfall[:72]), 1),
                "mean_shortwave_w_m2": (
                    round(sum(radiation[:72]) / len(radiation[:72]), 1) if radiation else None
                ),
                "variables": [
                    "precipitation", "temperature_2m", "shortwave_radiation",
                    "snowfall", "surface_pressure",
                ],
            }
        except Exception:
            return None

    async def get_rainfall(self, lat: float, lng: float) -> dict | None:
        """Hourly precipitation forecast (mm). Returns None on failure."""
        try:
            data = await self.fetch_with_retry(
                self.FORECAST_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "hourly": "precipitation,precipitation_probability",
                    "forecast_days": 7,
                },
            )
            hourly = data.get("hourly", {})
            precip = [p for p in hourly.get("precipitation", []) if p is not None]
            return {
                "peak_mm_h": max(precip) if precip else 0.0,
                "total_72h_mm": round(sum(precip[:72]), 1),
                "series": precip[:120],
                "times": hourly.get("time", [])[:120],
            }
        except Exception:
            return None

    async def get_historical_discharge(
        self, lat: float, lng: float, start_year: int = 1984
    ) -> dict | None:
        """Multi-decade GloFAS reanalysis daily discharge — for flood-frequency fits.

        The Open-Meteo flood API serves the GloFAS v4 reanalysis back to 1984
        (the same record Nearing et al. 2024 compute per-gauge return periods
        from). This is REFERENCE data for deriving basin-specific return-period
        thresholds, never a forecast-model input. Cached for 24h via a widened
        per-call TTL since the record only grows by one day per day. Returns
        None on failure.
        """
        from datetime import date, timedelta

        end = date.today() - timedelta(days=2)  # reanalysis lags realtime
        cache_key = self._cache_key("hist_discharge", round(lat, 2), round(lng, 2),
                                    start_year, end.isoformat())
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached
        try:
            data = await self.fetch_with_retry(
                self.FLOOD_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "daily": "river_discharge",
                    "start_date": f"{start_year}-01-01",
                    "end_date": end.isoformat(),
                },
            )
            daily = data.get("daily", {})
            result = {
                "time": daily.get("time", []),
                "discharge": daily.get("river_discharge", []),
            }
            # Long-lived manual cache entry (base TTL is 900s; this is daily
            # data): shift the stored timestamp forward so the standard TTL
            # check keeps it for ~24h.
            self._cache[cache_key] = (time.time() + 86400 - self._cache_ttl, result)
            return result
        except Exception:
            return None

    async def get_discharge_ensemble(self, lat: float, lng: float) -> dict | None:
        """GloFAS river-discharge ensemble percentiles — BENCHMARK REFERENCE ONLY.

        This is the system Nearing et al. (2024) benchmark against, not an input to
        the AI predictor (the paper uses no streamflow as input). Kept for side-by-
        side comparison/UI, never fed into the forecast. Returns None on failure.
        """
        try:
            data = await self.fetch_with_retry(
                self.FLOOD_BASE,
                params={
                    "latitude": lat, "longitude": lng,
                    "daily": ("river_discharge,river_discharge_mean,river_discharge_max,"
                              "river_discharge_p25,river_discharge_p75"),
                    "forecast_days": 30,
                },
            )
            daily = data.get("daily", {})
            return {
                "time": daily.get("time", []),
                "mean": daily.get("river_discharge_mean", []),
                "max": daily.get("river_discharge_max", []),
                "p25": daily.get("river_discharge_p25", []),
                "p75": daily.get("river_discharge_p75", []),
            }
        except Exception:
            return None
