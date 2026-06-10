"""
Offline tests for the flood-frequency engine (hydrology/return_periods.py),
the predict agent's GloFAS benchmark wiring, and the OpenAI-compatible
LLM providers (Groq/OpenRouter). No network access.
"""

from __future__ import annotations

import pytest

from floodops.hydrology.return_periods import (
    annual_maxima,
    classify_return_period,
    compute_return_period_thresholds,
)
from floodops.llm.providers import (
    NullProvider,
    OpenAICompatProvider,
    make_provider,
)

# ── Flood-frequency engine ──────────────────────────────────────────────

def test_annual_maxima_groups_by_year_and_skips_bad_values():
    times = ["2020-01-01", "2020-06-15", "2021-03-02", "2021-07-09", "bad", "2022-01-01"]
    values = [10.0, 42.0, 5.0, None, 99.0, float("nan")]
    maxima = annual_maxima(times, values)
    assert maxima == {2020: 42.0, 2021: 5.0}


def test_thresholds_monotonic_and_within_record_range():
    # 40 synthetic years: peaks growing 100..490 m³/s.
    maxima = [100.0 + 10.0 * i for i in range(40)]
    fit = compute_return_period_thresholds(maxima)
    assert fit is not None
    assert set(fit) == {1, 2, 5, 10}
    # Rarer events need bigger floods, and all estimates stay inside the record.
    assert fit[1] < fit[2] < fit[5] < fit[10]
    assert min(maxima) <= fit[1] and fit[10] <= max(maxima)


def test_thresholds_refused_on_short_or_degenerate_record():
    assert compute_return_period_thresholds([100.0] * 5) is None  # <10 yrs
    assert compute_return_period_thresholds([0.0] * 20) is None   # all zero


def test_classify_return_period():
    fit = {1: 100.0, 2: 150.0, 5: 220.0, 10: 300.0}
    assert classify_return_period(90.0, fit) is None
    assert classify_return_period(100.0, fit) == 1
    assert classify_return_period(219.0, fit) == 2
    assert classify_return_period(5000.0, fit) == 10


# ── Predict agent benchmark wiring (stub connector, no network) ─────────

class StubHydroConnector:
    """Returns a 40-yr synthetic record and a forecast peaking at a ~5-yr event."""

    def __init__(self):
        self.history_calls = 0

    async def fetch_latest(self, bbox=None, **kwargs):
        return {}  # predict's forcing path degrades to mock intensity

    async def get_historical_discharge(self, lat, lng, start_year=1984):
        self.history_calls += 1
        times, values = [], []
        for year in range(1984, 2024):
            times += [f"{year}-07-01", f"{year}-12-01"]
            values += [100.0 + 10.0 * (year - 1984), 20.0]
        return {"time": times, "discharge": values}

    async def get_discharge_ensemble(self, lat, lng):
        return {"time": ["d1", "d2"], "mean": [50.0, 400.0], "max": [60.0, 500.0],
                "p25": [], "p75": []}


@pytest.mark.asyncio
async def test_predict_attaches_glofas_benchmark_reference(fake_llm):
    from floodops.agents.predict import FloodPredictAgent
    from floodops.queue.event_bus import EventBus

    connector = StubHydroConnector()
    agent = FloodPredictAgent(EventBus(), llm=fake_llm, connector=connector)
    forecast = await agent.run_ensemble({"watershed_id": "bagmati",
                                         "location": {"lat": 27.7, "lng": 85.3}})
    assert forecast is not None
    fit = forecast.benchmark_discharge_thresholds_m3s
    assert fit is not None and fit[1] < fit[10]
    assert forecast.benchmark_peak_discharge_m3s == 400.0
    assert forecast.benchmark_return_period_years in (1, 2, 5, 10)
    assert "GloFAS benchmark" in (forecast.summary or "")

    # Thresholds are cached per basin — a second run must not refetch history.
    await agent.run_ensemble({"watershed_id": "bagmati",
                              "location": {"lat": 27.7, "lng": 85.3}})
    assert connector.history_calls == 1


@pytest.mark.asyncio
async def test_predict_benchmark_degrades_without_connector(fake_llm):
    from floodops.agents.predict import FloodPredictAgent
    from floodops.queue.event_bus import EventBus

    agent = FloodPredictAgent(EventBus(), llm=fake_llm, connector=None)
    forecast = await agent.run_ensemble({"watershed_id": "bagmati"})
    assert forecast is not None
    assert forecast.benchmark_discharge_thresholds_m3s is None
    assert forecast.benchmark_return_period_years is None


# ── OpenAI-compatible providers (no network calls made) ─────────────────

def test_openai_compat_unavailable_without_key():
    p = OpenAICompatProvider("groq", "https://api.groq.com/openai/v1", "", "llama")
    assert not p.available()


def test_make_provider_explicit_groq_and_openrouter():
    groq = make_provider("groq")
    assert groq.name == "groq"
    router = make_provider("openrouter")
    assert router.name == "openrouter"


def test_make_provider_auto_falls_back_to_null(monkeypatch):
    import floodops.llm.providers as providers

    # Force every backend to report unavailable regardless of local .env keys.
    monkeypatch.setattr(providers.AnthropicProvider, "available", lambda self: False)
    monkeypatch.setattr(providers.GeminiProvider, "available", lambda self: False)
    monkeypatch.setattr(providers.OpenAICompatProvider, "available", lambda self: False)
    assert isinstance(make_provider("auto"), NullProvider)
